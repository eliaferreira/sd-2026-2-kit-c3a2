"""
Testes ponta a ponta: falam com a plataforma de verdade, SEMPRE pelo gateway.

Servem para dois momentos:
  1. stack local:  docker compose up --build   ->  E2E_URL=http://localhost:8000
  2. deploy:       URL publica do free tier     ->  E2E_URL=https://<seu-app>.onrender.com

Variaveis:
  E2E_URL      endereco do gateway (obrigatoria; sem ela os testes sao pulados)
  E2E_TOKEN    token JWT pronto (opcional)
  JWT_SEGREDO  se E2E_TOKEN nao vier, gera um token HS256 com este segredo

Rodar:
  pip install -r tests/e2e/requirements.txt
  E2E_URL=http://localhost:8000 JWT_SEGREDO=<o do .env> pytest tests/e2e -v
"""
import os
import time
from urllib.parse import urlparse

import pytest
import requests

E2E_URL = os.getenv("E2E_URL", "").rstrip("/")
TIMEOUT = float(os.getenv("E2E_TIMEOUT", "30"))  # free tier "acorda" devagar

pytestmark = pytest.mark.skipif(
    not E2E_URL, reason="defina E2E_URL para rodar os testes ponta a ponta"
)


def _token():
    if os.getenv("E2E_TOKEN"):
        return os.environ["E2E_TOKEN"]
    segredo = os.getenv("JWT_SEGREDO")
    if not segredo:
        return None
    import jwt

    agora = int(time.time())
    return jwt.encode(
        {"sub": "teste-e2e", "iat": agora, "exp": agora + 300}, segredo, algorithm="HS256"
    )


@pytest.fixture(scope="module")
def auth():
    token = _token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def test_gateway_saudavel():
    resposta = requests.get(f"{E2E_URL}/saude", timeout=TIMEOUT)
    assert resposta.status_code == 200
    assert resposta.json().get("status") == "ok"


def test_predict_passa_pelo_gateway_ate_a_inferencia(auth):
    resposta = requests.post(
        f"{E2E_URL}/predict",
        json={"texto": "o atendimento foi excelente e muito rapido"},
        headers=auth,
        timeout=TIMEOUT,
    )
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["sentimento"] in ("positivo", "negativo")
    assert 0.0 <= float(dados["confianca"]) <= 1.0


def test_predict_texto_invalido_retorna_422(auth):
    resposta = requests.post(f"{E2E_URL}/predict", json={}, headers=auth, timeout=TIMEOUT)
    assert resposta.status_code == 422


def test_predict_sem_token_retorna_401():
    resposta = requests.post(f"{E2E_URL}/predict", json={"texto": "ok"}, timeout=TIMEOUT)
    assert resposta.status_code == 401


def test_processamento_assincrono(auth):
    if not auth:
        pytest.fail("Defina E2E_TOKEN ou JWT_SEGREDO para testar o fluxo autenticado")
    resposta = requests.post(f"{E2E_URL}/tarefas", json={"texto": "atendimento excelente"},
                             headers=auth, timeout=TIMEOUT)
    assert resposta.status_code == 202, resposta.text
    tarefa_id = resposta.json()["id"]
    limite = time.monotonic() + 60
    while time.monotonic() < limite:
        status = requests.get(f"{E2E_URL}/tarefas/{tarefa_id}", headers=auth, timeout=TIMEOUT)
        assert status.status_code == 200, status.text
        dados = status.json()
        if dados["status"] == "concluido":
            assert dados["resultado"]["sentimento"] in ("positivo", "negativo")
            return
        assert dados["status"] != "falhou", dados
        time.sleep(1)
    pytest.fail("Tarefa nao foi concluida em 60 segundos")


def test_url_publica_usa_https():
    """TAREFA 8: fora do localhost, o servico publicado precisa estar em HTTPS.
    O requests valida o certificado por padrao, entao um certificado invalido
    tambem derruba os demais testes."""
    host = urlparse(E2E_URL).hostname or ""
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        pytest.skip("ambiente local: HTTPS nao se aplica")
    assert urlparse(E2E_URL).scheme == "https"
