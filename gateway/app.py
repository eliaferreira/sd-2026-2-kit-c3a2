"""
API Gateway - porta de entrada unica da plataforma.

JA PRONTO: roteamento para o servico de inferencia e log de requisicoes.
TAREFA 1: autenticacao por JWT.
TAREFA 2: limite de requisicoes por cliente (rate limit).

Rodar: uvicorn app:app --port 8000
"""
import hmac
import os
import threading
import time
from collections import defaultdict, deque

import jwt
import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from resiliencia import (
    CircuitoAberto, ClienteInferencia, Configuracao, FalhaDependencia,
    RequisicaoRecusada,
)

app = FastAPI(title="Gateway - C3.A2")

URL_INFERENCIA = os.getenv("URL_INFERENCIA", "http://localhost:8001")
cliente_inferencia = ClienteInferencia(Configuracao.do_ambiente())

# --- Configuracao (tudo por variavel de ambiente; ver .env.example) ---------
# Nome da variavel segue o conftest dos testes (JWT_SEGREDO).
JWT_SEGREDO = os.getenv("JWT_SEGREDO", "dev-troque-este-segredo")
JWT_ALGORITMO = "HS256"
JWT_EXPIRA_MINUTOS = int(os.getenv("JWT_EXPIRA_MINUTOS", "30"))

# Credenciais de demonstracao do projeto academico (uma unica conta).
LOGIN_USUARIO = os.getenv("LOGIN_USUARIO", "admin")
LOGIN_SENHA = os.getenv("LOGIN_SENHA", "admin")

# Rate limit: no maximo RATE_LIMIT_MAX requisicoes a cada RATE_LIMIT_JANELA_S.
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "60"))
RATE_LIMIT_JANELA_S = float(os.getenv("RATE_LIMIT_JANELA_S", "60"))

if JWT_SEGREDO == "dev-troque-este-segredo":
    print("[gateway] AVISO: JWT_SEGREDO padrao em uso. Defina um segredo no .env.")


class Entrada(BaseModel):
    texto: str


class Credenciais(BaseModel):
    usuario: str
    senha: str


# --- Log de requisicoes (nunca registra corpo, texto ou credenciais) ---------
@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    resposta = await call_next(request)
    ms = (time.time() - inicio) * 1000
    print(f"[gateway] {request.method} {request.url.path} "
          f"-> {resposta.status_code} ({ms:.1f}ms)")
    return resposta


# --- TAREFA 1: JWT -----------------------------------------------------------
esquema_bearer = HTTPBearer(auto_error=False)


def criar_token(usuario: str) -> str:
    agora = int(time.time())
    payload = {
        "sub": usuario,
        "iat": agora,
        "exp": agora + JWT_EXPIRA_MINUTOS * 60,
    }
    return jwt.encode(payload, JWT_SEGREDO, algorithm=JWT_ALGORITMO)


def autenticar(
    credenciais: HTTPAuthorizationCredentials | None = Depends(esquema_bearer),
) -> str:
    """Exige um token JWT valido. Devolve o usuario (campo 'sub')."""
    nao_autorizado = HTTPException(
        status_code=401,
        detail="token ausente, invalido ou expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credenciais is None or credenciais.scheme.lower() != "bearer":
        raise nao_autorizado
    try:
        payload = jwt.decode(
            credenciais.credentials,
            JWT_SEGREDO,
            algorithms=[JWT_ALGORITMO],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        raise nao_autorizado
    return str(payload["sub"])


# --- TAREFA 2: rate limit (janela deslizante, em memoria) --------------------
_acessos: dict[str, deque] = defaultdict(deque)
_trava = threading.Lock()


def _checar_limite(chave: str) -> None:
    agora = time.monotonic()
    with _trava:
        fila = _acessos[chave]
        while fila and agora - fila[0] >= RATE_LIMIT_JANELA_S:
            fila.popleft()
        if len(fila) >= RATE_LIMIT_MAX:
            espera = max(1, int(RATE_LIMIT_JANELA_S - (agora - fila[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="limite de requisicoes excedido",
                headers={"Retry-After": str(espera)},
            )
        fila.append(agora)


def limitar_por_usuario(usuario: str = Depends(autenticar)) -> str:
    """Autentica e depois aplica o limite por usuario."""
    _checar_limite(f"usuario:{usuario}")
    return usuario


def limitar_por_ip(request: Request) -> None:
    """Limite por IP para rotas sem token (ex.: /login, contra forca bruta)."""
    ip = request.client.host if request.client else "desconhecido"
    _checar_limite(f"ip:{ip}")


# --- Rotas -------------------------------------------------------------------
@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/login", dependencies=[Depends(limitar_por_ip)])
def login(cred: Credenciais):
    usuario_ok = hmac.compare_digest(cred.usuario.encode(), LOGIN_USUARIO.encode())
    senha_ok = hmac.compare_digest(cred.senha.encode(), LOGIN_SENHA.encode())
    if not (usuario_ok and senha_ok):
        raise HTTPException(status_code=401, detail="usuario ou senha invalidos")
    return {
        "access_token": criar_token(cred.usuario),
        "token_type": "bearer",
        "expires_in": JWT_EXPIRA_MINUTOS * 60,
    }


@app.post("/predict")
def predict(entrada: Entrada, usuario: str = Depends(limitar_por_usuario)):
    try:
        return cliente_inferencia.prever(URL_INFERENCIA, entrada.model_dump())
    except RequisicaoRecusada as erro:
        raise HTTPException(status_code=erro.status_code,
                            detail="requisicao recusada pela inferencia") from None
    except CircuitoAberto as erro:
        raise HTTPException(status_code=503,
                            detail="servico de inferencia indisponivel",
                            headers={"Retry-After": str(erro.espera_s)}) from None
    except FalhaDependencia:
        raise HTTPException(status_code=503,
                            detail="servico de inferencia indisponivel") from None
