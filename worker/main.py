
"""
Worker de inferencia assincrona - C3.A2.

Consome tarefas do Redis, chama o servico de inferencia
e registra o resultado de cada processamento.
"""

import logging
import math
import os
import time

import requests
import redis

try:
    from . import fila
    from . import rastreamento
except ImportError:
    import fila
    import rastreamento


URL_INFERENCIA = os.getenv(
    "URL_INFERENCIA",
    "http://localhost:8001"
)

MAX_TENTATIVAS = int(os.getenv("WORKER_MAX_TENTATIVAS", "3"))
ESPERA_BASE_S = float(os.getenv("WORKER_BACKOFF_S", "0.5"))
TIMEOUT_S = float(os.getenv("WORKER_TIMEOUT_S", "3"))
if (MAX_TENTATIVAS < 1 or not math.isfinite(ESPERA_BASE_S) or ESPERA_BASE_S < 0
        or not math.isfinite(TIMEOUT_S) or TIMEOUT_S <= 0):
    raise ValueError("configuracao de resiliencia do worker invalida")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s"
)

log = logging.getLogger("worker")


def executar_inferencia(texto):
    """Solicita a classificacao de sentimento."""
    with rastreamento.span("worker", "inferencia.predict"):
        resposta = requests.post(
            f"{URL_INFERENCIA}/predict", json={"texto": texto}, timeout=TIMEOUT_S,
            allow_redirects=False, headers={"traceparent": rastreamento.cabecalho()},
        )
        try:
            resposta.raise_for_status()
            if 300 <= resposta.status_code < 400:
                raise requests.RequestException("redirecionamento de inferencia recusado")
            return resposta.json()
        finally:
            resposta.close()


def processar_tarefa(tarefa):
    """Um unico ciclo de retentativas, apenas para falhas transitorias."""
    ultimo_erro = None

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            return executar_inferencia(tarefa["texto"])
        except requests.RequestException as erro:
            status = erro.response.status_code if erro.response is not None else None
            transitorio = isinstance(erro, (requests.ConnectionError, requests.Timeout))
            if not transitorio and status not in {429, 500, 502, 503, 504}:
                raise
            ultimo_erro = erro

            log.warning(
                "Falha na tarefa %s, tentativa %s/%s",
                tarefa["id"],
                tentativa,
                MAX_TENTATIVAS
            )

            if tentativa < MAX_TENTATIVAS:
                time.sleep(ESPERA_BASE_S * 2 ** (tentativa - 1))

    raise ultimo_erro


def tratar_tarefa(tarefa):
    with rastreamento.span("worker", "fila.processar", pai=tarefa.get("traceparent", "")) as estado:
        if not _tratar_tarefa(tarefa):
            estado["resultado"] = "erro"


def _tratar_tarefa(tarefa):
    """Registra sucesso ou encaminha falhas para descarte."""
    tarefa_id = tarefa["id"]

    fila.guardar_status(
        tarefa_id,
        {"status": "processando"}
    )

    try:
        resultado = processar_tarefa(tarefa)

    except Exception as erro:
        # Excecoes HTTP podem incluir URL/corpo; guardar apenas a categoria.
        mensagem = f"falha no processamento ({type(erro).__name__})"
        log.error("Tarefa %s: %s", tarefa_id, mensagem)

        fila.enviar_para_descarte(tarefa, mensagem)

        fila.guardar_status(
            tarefa_id,
            {
                "status": "falhou",
                "erro": mensagem
            }
        )
        return False

    fila.guardar_status(
        tarefa_id,
        {
            "status": "concluido",
            "resultado": resultado
        }
    )

    log.info("Tarefa %s concluida", tarefa_id)
    return True


def main():
    """Mantem o worker aguardando novas tarefas."""
    log.info("Worker iniciado, aguardando tarefas...")

    while True:
        try:
            tarefa = fila.consumir_tarefa(timeout=5)

            if tarefa is not None:
                tratar_tarefa(tarefa)

        except redis.RedisError as erro:
            log.error("Falha de comunicacao com Redis: %s", erro)
            time.sleep(2)


if __name__ == "__main__":
    main()
