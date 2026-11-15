"""
Script de treinamento reproduzivel do modelo de sentimento.

Le o dataset versionado em dados_treino.csv, treina o pipeline scikit-learn
com semente fixa e salva o artefato no caminho configurado em MODEL_PATH.

Rodar: python treinar.py
"""
import csv
import os
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

DIRETORIO_BASE = os.path.dirname(os.path.abspath(__file__))
CAMINHO_DADOS = os.path.join(DIRETORIO_BASE, "dados_treino.csv")
CAMINHO_PADRAO_MODELO = os.path.join(DIRETORIO_BASE, "modelo.joblib")


def carregar_dados_treino(caminho_csv: str = CAMINHO_DADOS) -> tuple[list[str], list[int]]:
    textos: list[str] = []
    rotulos: list[int] = []
    with open(caminho_csv, mode="r", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        for linha in leitor:
            textos.append(linha["texto"])
            rotulos.append(int(linha["rotulo"]))
    return textos, rotulos


def treinar_e_salvar(caminho_modelo: str | None = None) -> str:
    destino = caminho_modelo or os.getenv("MODEL_PATH", CAMINHO_PADRAO_MODELO)
    textos, rotulos = carregar_dados_treino()

    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=1),
        LogisticRegression(max_iter=1000, random_state=42),
    )
    pipe.fit(textos, rotulos)

    diretorio_destino = os.path.dirname(os.path.abspath(destino))
    if diretorio_destino:
        os.makedirs(diretorio_destino, exist_ok=True)
    joblib.dump(pipe, destino)
    return destino


if __name__ == "__main__":
    caminho_salvo = treinar_e_salvar()
    print(f"[treino] Modelo treinado e salvo com sucesso em: {caminho_salvo}")
