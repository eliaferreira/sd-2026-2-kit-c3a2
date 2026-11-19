"""
Configuracao compartilhada dos testes do gateway.

Os testes NAO dependem do servico de inferencia no ar: a chamada HTTP do
gateway para a inferencia e substituida por um dublê (monkeypatch).
"""
import os
import sys
import time

import jwt
import pytest

DIRETORIO_GATEWAY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DIRETORIO_GATEWAY not in sys.path:
    sys.path.insert(0, DIRETORIO_GATEWAY)

# Segredo fixo apenas para testes; precisa existir antes de importar o app.
JWT_SEGREDO_TESTE = "segredo-somente-para-testes"
os.environ.setdefault("JWT_SEGREDO", JWT_SEGREDO_TESTE)
os.environ.setdefault("URL_INFERENCIA", "http://inferencia-falsa:8001")

import app as app_modulo  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app_modulo.app)


@pytest.fixture
def token_valido():
    """Token HS256 assinado com JWT_SEGREDO (mesmo segredo que o gateway le)."""
    agora = int(time.time())
    return jwt.encode(
        {"sub": "usuario-teste", "iat": agora, "exp": agora + 300},
        os.environ["JWT_SEGREDO"],
        algorithm="HS256",
    )


@pytest.fixture
def auth(token_valido):
    """Cabecalho de autenticacao. Enviado em todas as chamadas a rotas protegidas,
    para que estes testes continuem validos depois que o JWT (TAREFA 1) entrar."""
    return {"Authorization": f"Bearer {token_valido}"}


class RespostaFalsa:
    """Imita requests.Response no que o gateway usa."""

    def __init__(self, status_code=200, corpo=None):
        self.status_code = status_code
        self._corpo = corpo or {}

    def json(self):
        return self._corpo

    def raise_for_status(self):
        import requests

        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} erro na inferencia")


@pytest.fixture
def inferencia_falsa(monkeypatch):
    """Substitui requests.post do gateway e registra as chamadas feitas."""
    chamadas = []
    estado = {"resposta": RespostaFalsa(200, {
        "texto": "servico excelente",
        "sentimento": "positivo",
        "confianca": 0.91,
    }), "erro": None}

    def post_falso(url, **kwargs):
        chamadas.append({"url": url, **kwargs})
        if estado["erro"] is not None:
            raise estado["erro"]
        return estado["resposta"]

    monkeypatch.setattr(app_modulo.requests, "post", post_falso)
    estado["chamadas"] = chamadas
    return estado
