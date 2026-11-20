"""
Testes automatizados para ingestao, busca vetorial, remocao e resiliencia a falhas.
"""
import math
import os
import sys

import pytest
from fastapi.testclient import TestClient

DIRETORIO_INFERENCIA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DIRETORIO_INFERENCIA not in sys.path:
    sys.path.insert(0, DIRETORIO_INFERENCIA)

import treinar  # noqa: E402

if not os.path.exists(treinar.config.obter_model_path()):
    treinar.treinar_e_salvar()

import app as app_modulo  # noqa: E402
from armazenamento_vetorial import (  # noqa: E402
    ArmazenamentoVetorial,
    ErroArmazenamentoVetorial,
)


def _similaridade_cosseno(v1: list[float], v2: list[float]) -> float:
    prod = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return prod / (n1 * n2)


class ArmazenamentoVetorialFalso:
    """Implementacao em memoria da interface ArmazenamentoVetorial para testes."""

    def __init__(self, indisponivel: bool = False):
        self.indisponivel = indisponivel
        self._dados: dict[str, tuple[list[float], dict]] = {}

    def _verificar_disponibilidade(self) -> None:
        if self.indisponivel:
            raise ErroArmazenamentoVetorial("banco vetorial indisponivel")

    def garantir_colecao(self) -> None:
        self._verificar_disponibilidade()

    def inserir(self, doc_id: str, vetor: list[float], metadados: dict) -> str:
        self._verificar_disponibilidade()
        self._dados[doc_id] = (vetor, metadados)
        return doc_id

    def buscar(self, vetor: list[float], k: int = 3) -> list[dict]:
        self._verificar_disponibilidade()
        pontuados = []
        for doc_id, (vec_salvo, meta) in self._dados.items():
            score = _similaridade_cosseno(vetor, vec_salvo)
            pontuados.append(
                {
                    "id": doc_id,
                    "score": round(float(score), 4),
                    "texto": meta.get("texto", ""),
                }
            )
        pontuados.sort(key=lambda item: item["score"], reverse=True)
        return pontuados[:k]

    def remover(self, doc_id: str) -> None:
        self._verificar_disponibilidade()
        self._dados.pop(doc_id, None)

    def saudavel(self) -> bool:
        return not self.indisponivel


@pytest.fixture
def store_falso(monkeypatch):
    falso = ArmazenamentoVetorialFalso()
    monkeypatch.setattr(app_modulo, "armazenamento", falso)
    return falso


@pytest.fixture
def client(store_falso):
    return TestClient(app_modulo.app)


def test_inserir_e_buscar_devolve_mais_similar_primeiro(client):
    r1 = client.post("/documentos", json={"texto": "entrega rapida e embalagem perfeita"})
    r2 = client.post("/documentos", json={"texto": "suporte nunca responde aos chamados"})
    r3 = client.post("/documentos", json={"texto": "produto quebrou no primeiro dia de uso"})

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 201

    id_esperado = r1.json()["id"]
    resposta = client.post(
        "/buscar",
        json={"texto": "entrega muito rapida e embalagem perfeita", "k": 3},
    )
    assert resposta.status_code == 200
    resultados = resposta.json()["resultados"]
    assert len(resultados) == 3
    assert resultados[0]["id"] == id_esperado
    assert resultados[0]["texto"] == "entrega rapida e embalagem perfeita"
    assert resultados[0]["score"] >= resultados[1]["score"]


def test_buscar_respeita_parametro_k(client):
    for i in range(4):
        res = client.post("/documentos", json={"texto": f"documento de teste numero {i}"})
        assert res.status_code == 201

    resposta = client.post("/buscar", json={"texto": "documento de teste", "k": 2})
    assert resposta.status_code == 200
    assert len(resposta.json()["resultados"]) == 2


@pytest.mark.parametrize("k_invalido", [0, -1, 21, 100])
def test_buscar_k_invalido_retorna_422(client, k_invalido):
    resposta = client.post("/buscar", json={"texto": "consulta valida", "k": k_invalido})
    assert resposta.status_code == 422


def test_remover_documento(client):
    r1 = client.post("/documentos", json={"texto": "documento temporario para remocao"})
    doc_id = r1.json()["id"]

    r_del = client.delete(f"/documentos/{doc_id}")
    assert r_del.status_code == 200
    assert r_del.json() == {"id": doc_id, "removido": True}

    r_busca = client.post("/buscar", json={"texto": "documento temporario", "k": 5})
    assert r_busca.status_code == 200
    assert r_busca.json()["resultados"] == []


def test_falha_do_store_retorna_503_e_predict_continua_funcionando(client, store_falso):
    store_falso.indisponivel = True

    r_saude = client.get("/saude")
    assert r_saude.status_code == 200
    assert r_saude.json() == {"status": "ok", "vetorial": "indisponivel"}

    r_doc = client.post("/documentos", json={"texto": "tentando gravar com banco fora"})
    assert r_doc.status_code == 503
    assert r_doc.json() == {"detail": "banco vetorial indisponivel"}

    r_busca = client.post("/buscar", json={"texto": "tentando buscar com banco fora", "k": 3})
    assert r_busca.status_code == 503
    assert r_busca.json() == {"detail": "banco vetorial indisponivel"}

    r_del = client.delete("/documentos/id-qualquer")
    assert r_del.status_code == 503

    r_predict = client.post("/predict", json={"texto": "o atendimento foi excelente"})
    assert r_predict.status_code == 200
    assert r_predict.json()["sentimento"] == "positivo"


def test_retentativa_recupera_de_falha_transitoria():
    class ClienteInstavel:
        def __init__(self):
            self.chamadas = 0

        def collection_exists(self, _nome):
            self.chamadas += 1
            if self.chamadas < 3:
                raise ConnectionError("falha temporaria de rede")
            return True

        def upsert(self, **_kwargs):
            return None

    cliente_instavel = ClienteInstavel()
    store = ArmazenamentoVetorial(
        cliente=cliente_instavel,
        max_tentativas=3,
        espera_base_s=0.01,
    )
    doc_id = store.inserir("id-1", [0.1] * store.dimensao, {"texto": "teste"})
    assert doc_id == "id-1"
    assert cliente_instavel.chamadas == 3


def _qdrant_local_disponivel() -> bool:
    store = ArmazenamentoVetorial(timeout=0.3)
    return store.saudavel()


@pytest.mark.skipif(not _qdrant_local_disponivel(), reason="Qdrant local nao disponivel")
def test_integracao_qdrant_real():
    store = ArmazenamentoVetorial(colecao="teste_integracao_c3a2", timeout=2.0)
    vetor = [1.0] + [0.0] * (store.dimensao - 1)
    store.inserir("00000000-0000-0000-0000-000000000001", vetor, {"texto": "integracao real"})
    res = store.buscar(vetor, k=1)
    assert len(res) >= 1
    assert res[0]["texto"] == "integracao real"
