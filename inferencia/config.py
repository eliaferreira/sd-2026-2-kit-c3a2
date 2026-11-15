"""
Configuracao centralizada do servico de inferencia via variaveis de ambiente.
"""
import os

DIRETORIO_BASE = os.path.dirname(os.path.abspath(__file__))

SERVICO_NOME = os.getenv("OTEL_SERVICE_NAME", "inferencia")
SERVICO_VERSAO = os.getenv("SERVICO_VERSAO", "0.1.0")

MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(DIRETORIO_BASE, "modelo.joblib"))
DADOS_TREINO_PATH = os.getenv(
    "DADOS_TREINO_PATH", os.path.join(DIRETORIO_BASE, "dados_treino.csv")
)
TREINO_MAX_ITER = int(os.getenv("TREINO_MAX_ITER", "1000"))
TREINO_RANDOM_STATE = int(os.getenv("TREINO_RANDOM_STATE", "42"))

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLECAO = os.getenv("QDRANT_COLECAO", "documentos")
TIMEOUT_VETORIAL = float(os.getenv("TIMEOUT_VETORIAL", "5.0"))
VETOR_DIMENSAO = int(os.getenv("VETOR_DIMENSAO", "256"))
VETORIAL_MAX_TENTATIVAS = int(os.getenv("VETORIAL_MAX_TENTATIVAS", "3"))
VETORIAL_ESPERA_BASE_S = float(os.getenv("VETORIAL_ESPERA_BASE_S", "0.5"))
BUSCA_K_PADRAO = int(os.getenv("BUSCA_K_PADRAO", "3"))
BUSCA_K_MAX = int(os.getenv("BUSCA_K_MAX", "20"))


def obter_model_path() -> str:
    """Retorna o caminho do modelo respeitando sobrescritas em tempo de execucao."""
    return os.getenv("MODEL_PATH", MODEL_PATH)


def obter_dados_treino_path() -> str:
    """Retorna o caminho dos dados de treino respeitando sobrescritas em tempo de execucao."""
    return os.getenv("DADOS_TREINO_PATH", DADOS_TREINO_PATH)
