"""
Camada de acesso ao banco vetorial (Qdrant).

Encapsula todas as chamadas ao qdrant-client para isolar a aplicacao
e permitir substituicao por implementacao em memoria nos testes.
"""
from qdrant_client import QdrantClient, models

import config


class ArmazenamentoVetorial:
    """Interface de acesso ao Qdrant para insercao, busca por similaridade e remocao."""

    def __init__(
        self,
        url: str | None = None,
        colecao: str | None = None,
        dimensao: int | None = None,
        timeout: float | None = None,
        cliente: QdrantClient | None = None,
    ):
        self.url = url or config.QDRANT_URL
        self.colecao = colecao or config.QDRANT_COLECAO
        self.dimensao = dimensao or config.VETOR_DIMENSAO
        self.timeout = timeout if timeout is not None else config.TIMEOUT_VETORIAL
        self._cliente = cliente or QdrantClient(url=self.url, timeout=self.timeout)
        self._colecao_garantida = False

    def garantir_colecao(self) -> None:
        """Cria a colecao com distancia cosseno caso ainda nao exista."""
        if self._colecao_garantida:
            return
        if not self._cliente.collection_exists(self.colecao):
            self._cliente.create_collection(
                collection_name=self.colecao,
                vectors_config=models.VectorParams(
                    size=self.dimensao,
                    distance=models.Distance.COSINE,
                ),
            )
        self._colecao_garantida = True

    def inserir(self, doc_id: str, vetor: list[float], metadados: dict) -> str:
        """Insere ou atualiza um documento vetorizado na colecao."""
        self.garantir_colecao()
        self._cliente.upsert(
            collection_name=self.colecao,
            points=[
                models.PointStruct(
                    id=doc_id,
                    vector=vetor,
                    payload=metadados,
                )
            ],
        )
        return doc_id

    def buscar(self, vetor: list[float], k: int = config.BUSCA_K_PADRAO) -> list[dict]:
        """Busca os k documentos mais similares usando distancia cosseno."""
        self.garantir_colecao()
        resposta = self._cliente.query_points(
            collection_name=self.colecao,
            query=vetor,
            limit=k,
            with_payload=True,
        )
        return [
            {
                "id": str(ponto.id),
                "score": round(float(ponto.score), 4),
                "texto": (ponto.payload or {}).get("texto", ""),
            }
            for ponto in resposta.points
        ]

    def remover(self, doc_id: str) -> None:
        """Remove um documento pelo id (atendimento ao direito de eliminacao - LGPD)."""
        self.garantir_colecao()
        self._cliente.delete(
            collection_name=self.colecao,
            points_selector=models.PointIdsList(points=[doc_id]),
        )

    def saudavel(self) -> bool:
        """Verifica se o banco vetorial esta acessivel e respondendo."""
        try:
            self._cliente.get_collections()
            return True
        except Exception:
            return False
