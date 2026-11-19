"""
Criterios de aceite de seguranca do gateway (TAREFAS 1 e 2).

Enquanto JWT e rate limit nao forem implementados, estes testes ficam marcados
como xfail (falha esperada) e nao quebram o CI. Quando a implementacao entrar,
eles passam a aparecer como XPASS: ai basta remover o marcador correspondente.

Premissas combinadas com o gateway:
- token no cabecalho "Authorization: Bearer <token>"
- assinatura HS256 com o segredo da variavel JWT_SEGREDO
- rate limit responde 429 quando o cliente passa do limite por minuto
"""
import time

import jwt
import pytest

AGUARDANDO_JWT = pytest.mark.xfail(
    reason="TAREFA 1 (JWT no gateway) ainda nao implementada", strict=False
)
AGUARDANDO_RATE_LIMIT = pytest.mark.xfail(
    reason="TAREFA 2 (rate limit no gateway) ainda nao implementada", strict=False
)


@AGUARDANDO_JWT
def test_predict_sem_token_retorna_401(client, inferencia_falsa):
    resposta = client.post("/predict", json={"texto": "ok"})
    assert resposta.status_code == 401
    assert inferencia_falsa["chamadas"] == []


@AGUARDANDO_JWT
def test_predict_com_token_de_outro_segredo_retorna_401(client, inferencia_falsa):
    falso = jwt.encode({"sub": "invasor"}, "segredo-errado", algorithm="HS256")
    resposta = client.post(
        "/predict", json={"texto": "ok"}, headers={"Authorization": f"Bearer {falso}"}
    )
    assert resposta.status_code == 401


@AGUARDANDO_JWT
def test_predict_com_token_expirado_retorna_401(client, inferencia_falsa):
    import os

    expirado = jwt.encode(
        {"sub": "usuario-teste", "exp": int(time.time()) - 60},
        os.environ["JWT_SEGREDO"],
        algorithm="HS256",
    )
    resposta = client.post(
        "/predict", json={"texto": "ok"}, headers={"Authorization": f"Bearer {expirado}"}
    )
    assert resposta.status_code == 401


@AGUARDANDO_JWT
def test_rota_de_login_existe(client):
    rotas = {getattr(r, "path", None) for r in client.app.routes}
    assert "/login" in rotas


def test_saude_continua_publica(client):
    """/saude precisa responder sem token (usado pelo healthcheck e pelo deploy)."""
    assert client.get("/saude").status_code == 200


@AGUARDANDO_RATE_LIMIT
def test_excesso_de_requisicoes_retorna_429(client, auth, inferencia_falsa):
    # Mantido por ultimo no arquivo: esgota a cota do cliente de teste.
    codigos = [
        client.post("/predict", json={"texto": "ok"}, headers=auth).status_code
        for _ in range(200)
    ]
    assert 429 in codigos
