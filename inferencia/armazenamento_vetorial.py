"""
Camada de acesso ao banco vetorial (Qdrant) com timeout, retentativa
com espera progressiva (backoff exponencial) e degradacao controlada.
"""
import time
from typing import Callable, TypeVar

from qdrant_client import QdrantClient, models

import config

T = TypeVar("T")


class ErroArmazenamentoVetorial(Exception):
    """Excecao levantada quando o banco vetorial esta indisponivel apos retentativas."""


class ArmazenamentoVetorial:
    """Interface resiliente de acesso ao Qdrant para insercao, busca e remocao."""

    def __init__(
        self,
        url: str | None = None,
        colecao: str | None = None,
        dimensao: int | None = None,
        timeout: float | None = None,
        max_tentativas: int | None = None,
        espera_base_s: float | None = None,
        cliente: QdrantClient | None = None,
    ):
        self.url = url or config.QDRANT_URL
        self.colecao = colecao or config.QDRANT_COLECAO
        self.dimensao = dimensao or config.VETOR_DIMENSAO
        self.timeout = timeout if timeout is not None else config.TIMEOUT_VETORIAL
        self.max_tentativas = (
            max_tentativas if max_tentativas is not None else config.VETORIAL_MAX_TENTATIVAS
        )
        self.espera_base_s = (
            espera_base_s if espera_base_s is not None else config.VETORIAL_ESPERA_BASE_S
        )
        self._cliente = cliente or QdrantClient(url=self.url, timeout=self.timeout)
        self._colecao_garantida = False

    def _executar_com_retentativa(self, operacao: Callable[[], T]) -> T:
        """Executa uma operacao idempotente com retentativa e backoff exponencial."""
        ultimo_erro: Exception | None = None
        tentativas = max(1, self.max_tentativas)
        for tentativa in range(1, tentativas + 1):
            try:
                return operacao()
            except Exception as exc:  # noqa: BLE001
                ultimo_erro = exc
                self._colecao_garantida = False
                if tentativa < tentativas and self.espera_base_s > 0:
                    atraso = self.espera_base_s * (2 ** (tentativa - 1))
                    time.sleep(atraso)
        raise ErroArmazenamentoVetorial("banco vetorial indisponivel") from ultimo_erro

    def _garantir_colecao_uma_vez(self) -> None:
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

    def garantir_colecao(self) -> None:
        """Cria a colecao com distancia cosseno usando retentativa."""
        self._executar_com_retentativa(self._garantir_colecao_uma_vez)

    def inserir(self, doc_id: str, vetor: list[float], metadados: dict) -> str:
        """Insere ou atualiza um documento vetorizado na colecao (idempotente por doc_id)."""
        def _op() -> str:
            self._garantir_colecao_uma_vez()
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

        return self._executar_com_retentativa(_op)

    def buscar(self, vetor: list[float], k: int = config.BUSCA_K_PADRAO) -> list[dict]:
        """Busca os k documentos mais similares usando distancia cosseno."""
        def _op() -> list[dict]:
            self._garantir_colecao_uma_vez()
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

        return self._executar_com_retentativa(_op)

    def remover(self, doc_id: str) -> None:
        """Remove um documento pelo id (atendimento ao direito de eliminacao - LGPD)."""
        def _op() -> None:
            self._garantir_colecao_uma_vez()
            self._cliente.delete(
                collection_name=self.colecao,
                points_selector=models.PointIdsList(points=[doc_id]),
            )

        self._executar_com_retentativa(_op)

    def saudavel(self) -> bool:
        """Verifica se o banco vetorial esta acessivel e respondendo."""
        try:
            self._cliente.get_collections()
            return True
        except Exception:
            self._colecao_garantida = False
            return False
