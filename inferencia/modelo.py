"""
Carregamento e inferencia do modelo de sentimento.

O modelo deve ser gerado previamente executando:
    python treinar.py
"""
import os
import joblib

import config


class ModeloSentimento:
    """Envolve o pipeline treinado. Use apenas o metodo prever()."""

    def __init__(self, pipeline):
        self._pipeline = pipeline

    def prever(self, texto: str) -> dict:
        """Recebe um texto e devolve o rotulo e a confianca."""
        proba = self._pipeline.predict_proba([texto])[0]
        idx = int(proba.argmax())
        return {
            "texto": texto,
            "sentimento": "positivo" if idx == 1 else "negativo",
            "confianca": round(float(proba[idx]), 4),
        }


def carregar_modelo(caminho: str | None = None) -> ModeloSentimento:
    """Carrega o modelo do disco. Falha com instrucao clara se nao existir."""
    caminho_efetivo = caminho or config.obter_model_path()
    if not os.path.exists(caminho_efetivo):
        raise FileNotFoundError(
            f"Arquivo de modelo nao encontrado em '{caminho_efetivo}'. "
            "Execute 'python treinar.py' antes de iniciar o servico."
        )
    pipe = joblib.load(caminho_efetivo)
    return ModeloSentimento(pipe)
