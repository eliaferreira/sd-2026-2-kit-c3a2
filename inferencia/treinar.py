"""
Script de treinamento reproduzivel do modelo de sentimento.

Le o dataset versionado em DADOS_TREINO_PATH, treina o pipeline scikit-learn
com semente fixa e salva o artefato no caminho configurado em MODEL_PATH.

Rodar: python treinar.py
"""
import csv
import os
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

import config


def carregar_dados_treino(caminho_csv: str | None = None) -> tuple[list[str], list[int]]:
    caminho_efetivo = caminho_csv or config.obter_dados_treino_path()
    textos: list[str] = []
    rotulos: list[int] = []
    with open(caminho_efetivo, mode="r", encoding="utf-8") as f:
        leitor = csv.DictReader(f)
        for linha in leitor:
            textos.append(linha["texto"])
            rotulos.append(int(linha["rotulo"]))
    return textos, rotulos


def treinar_e_salvar(caminho_modelo: str | None = None) -> str:
    destino = caminho_modelo or config.obter_model_path()
    textos, rotulos = carregar_dados_treino()

    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=1),
        LogisticRegression(
            max_iter=config.TREINO_MAX_ITER,
            random_state=config.TREINO_RANDOM_STATE,
        ),
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
