"""
Vetorizacao leve e deterministica de textos usando HashingVectorizer (scikit-learn).

Funciona 100% offline, sem download de modelos externos e com consumo minimo de RAM.
"""
from sklearn.feature_extraction.text import HashingVectorizer

import config

_vetorizador = HashingVectorizer(
    n_features=config.VETOR_DIMENSAO,
    norm="l2",
    alternate_sign=False,
    ngram_range=(1, 2),
)


def vetorizar(texto: str) -> list[float]:
    """Transforma um texto em um vetor denso normalizado (L2) de dimensao fixa."""
    matriz = _vetorizador.transform([texto])
    vetor = matriz.toarray()[0]
    return [float(x) for x in vetor]
