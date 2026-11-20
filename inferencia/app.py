"""
Servico de inferencia - C3.A2.

Rodar: uvicorn app:app --port 8001
"""
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

import config
from modelo import carregar_modelo

app = FastAPI(title=config.SERVICO_NOME, version=config.SERVICO_VERSAO)

modelo = carregar_modelo()


class Entrada(BaseModel):
    texto: str

    @field_validator("texto")
    @classmethod
    def validar_texto_nao_vazio(cls, valor: str) -> str:
        texto_limpo = valor.strip()
        if not texto_limpo:
            raise ValueError("O campo 'texto' nao pode ser vazio.")
        return texto_limpo


@app.exception_handler(Exception)
async def tratar_erro_inesperado(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "erro interno no servico de inferencia"},
    )


@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    try:
        resposta = await call_next(request)
    except Exception:
        resposta = JSONResponse(
            status_code=500,
            content={"detail": "erro interno no servico de inferencia"},
        )
    ms = (time.time() - inicio) * 1000
    print(
        f"[inferencia] {request.method} {request.url.path} "
        f"-> {resposta.status_code} ({ms:.1f}ms)"
    )
    return resposta


@app.get("/saude")
def saude():
    return {"status": "ok"}


@app.post("/predict")
def predict(entrada: Entrada):
    """Inferencia sincrona: recebe texto e devolve sentimento e confianca."""
    inicio = time.time()
    resultado = modelo.prever(entrada.texto)
    resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    return resultado
