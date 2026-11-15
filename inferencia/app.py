"""
Servico de inferencia - importado do C1.A2 e adaptado para C3.A2.

Rodar: uvicorn app:app --port 8001
"""
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from modelo import carregar_modelo

app = FastAPI(title="Servico de Inferencia - C3.A2", version="0.1.0")

modelo = carregar_modelo()


class Entrada(BaseModel):
    texto: str


@app.get("/saude")
def saude():
    return {"status": "ok", "modelo_carregado": modelo is not None}


@app.post("/predict")
def predict(entrada: Entrada):
    """Inferencia sincrona: recebe texto e devolve sentimento e confianca."""
    if not entrada.texto.strip():
        raise HTTPException(status_code=400, detail="texto vazio")
    inicio = time.time()
    resultado = modelo.prever(entrada.texto)
    resultado["tempo_ms"] = round((time.time() - inicio) * 1000, 2)
    return resultado
