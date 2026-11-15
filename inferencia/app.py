"""
Servico de inferencia e armazenamento vetorial - C3.A2.

Rodar: uvicorn app:app --port 8001
"""
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import config
from armazenamento_vetorial import ArmazenamentoVetorial, ErroArmazenamentoVetorial
from modelo import carregar_modelo
from vetorizador import vetorizar

app = FastAPI(title=config.SERVICO_NOME, version=config.SERVICO_VERSAO)

modelo = carregar_modelo()
armazenamento = ArmazenamentoVetorial()


def obter_armazenamento():
    return armazenamento


class Entrada(BaseModel):
    texto: str

    @field_validator("texto")
    @classmethod
    def validar_texto_nao_vazio(cls, valor: str) -> str:
        texto_limpo = valor.strip()
        if not texto_limpo:
            raise ValueError("O campo 'texto' nao pode ser vazio.")
        return texto_limpo


class EntradaBusca(Entrada):
    k: int = Field(default=config.BUSCA_K_PADRAO, ge=1, le=config.BUSCA_K_MAX)


@app.exception_handler(ErroArmazenamentoVetorial)
async def tratar_erro_vetorial(request: Request, exc: ErroArmazenamentoVetorial):
    return JSONResponse(
        status_code=503,
        content={"detail": "banco vetorial indisponivel"},
    )


@app.exception_handler(Exception)
async def tratar_erro_inesperado(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": "erro interno no servico de inferencia"},
    )


@app.middleware("http")
async def registrar(request: Request, call_next):
    inicio = time.time()
    traceparent = request.headers.get("traceparent")
    try:
        resposta = await call_next(request)
    except ErroArmazenamentoVetorial:
        resposta = JSONResponse(
            status_code=503,
            content={"detail": "banco vetorial indisponivel"},
        )
    except Exception:
        resposta = JSONResponse(
            status_code=500,
            content={"detail": "erro interno no servico de inferencia"},
        )
    if traceparent:
        resposta.headers["traceparent"] = traceparent
    ms = (time.time() - inicio) * 1000
    print(
        f"[{config.SERVICO_NOME}] {request.method} {request.url.path} "
        f"-> {resposta.status_code} ({ms:.1f}ms)"
    )
    return resposta


@app.get("/saude")
def saude():
    estado_vetorial = "ok" if obter_armazenamento().saudavel() else "indisponivel"
    return {"status": "ok", "vetorial": estado_vetorial}


@app.post("/predict")
def predict(entrada: Entrada):
    """Inferencia sincrona: recebe texto e devolve sentimento e confianca (independente do Qdrant)."""
    inicio = time.time()
    resultado = modelo.prever(entrada.texto)
    resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    return resultado


@app.post("/documentos", status_code=201)
def indexar_documento(entrada: Entrada):
    """Vetoriza um texto e armazena no banco vetorial."""
    doc_id = str(uuid.uuid4())
    vetor = vetorizar(entrada.texto)
    obter_armazenamento().inserir(doc_id, vetor, {"texto": entrada.texto})
    return {"id": doc_id}


@app.post("/buscar")
def buscar_documentos(entrada: EntradaBusca):
    """Busca os k documentos mais similares ao texto informado."""
    vetor = vetorizar(entrada.texto)
    resultados = obter_armazenamento().buscar(vetor, k=entrada.k)
    return {"resultados": resultados}


@app.delete("/documentos/{doc_id}")
def remover_documento(doc_id: str):
    """Remove um documento do banco vetorial pelo id (direito de eliminacao - LGPD)."""
    obter_armazenamento().remover(doc_id)
    return {"id": doc_id, "removido": True}
