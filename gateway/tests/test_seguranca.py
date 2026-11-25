"""
Criterios de aceite de seguranca do gateway (TAREFAS 1 e 2).

JWT e rate limit ja estao implementados no gateway, entao estes testes sao
obrigatorios: se algum falhar, o CI quebra.

Premissas combinadas com o gateway:
- token no cabecalho "Authorization: Bearer <token>"
- assinatura HS256 com o segredo da variavel JWT_SEGREDO
- rate limit responde 429 quando o cliente passa do limite por minuto
"""
import os
import time

import jwt


def test_predict_sem_token_retorna_401(client, inferencia_falsa):
    resposta = client.post("/predict", json={"texto": "ok"})
    assert resposta.status_code == 401
    assert inferencia_falsa["chamadas"] == []


def test_predict_com_token_de_outro_segredo_retorna_401(client, inferencia_falsa):
    falso = jwt.encode({"sub": "invasor"}, "segredo-errado", algorithm="HS256")
    resposta = client.post(
        "/predict", json={"texto": "ok"}, headers={"Authorization": f"Bearer {falso}"}
    )
    assert resposta.status_code == 401


def test_predict_com_token_expirado_retorna_401(client, inferencia_falsa):
    expirado = jwt.encode(
        {"sub": "usuario-teste", "exp": int(time.time()) - 60},
        os.environ["JWT_SEGREDO"],
        algorithm="HS256",
    )
    resposta = client.post(
        "/predict", json={"texto": "ok"}, headers={"Authorization": f"Bearer {expirado}"}
    )
    assert resposta.status_code == 401


def test_rota_de_login_existe(client):
    rotas = {getattr(r, "path", None) for r in client.app.routes}
    assert "/login" in rotas


def test_saude_continua_publica(client):
    """/saude precisa responder sem token (usado pelo healthcheck e pelo deploy)."""
    assert client.get("/saude").status_code == 200


def test_excesso_de_requisicoes_retorna_429(client, auth, inferencia_falsa):
    # Mantido por ultimo no arquivo: esgota a cota do cliente de teste.
    codigos = [
        client.post("/predict", json={"texto": "ok"}, headers=auth).status_code
        for _ in range(200)
    ]
    assert 429 in codigos