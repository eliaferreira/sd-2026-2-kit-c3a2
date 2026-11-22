
"""
Worker de inferencia assincrona - C3.A2.

Consome tarefas do Redis, chama o servico de inferencia
e registra o resultado de cada processamento.
"""

import logging
import os
import time

import requests
import redis

try:
    from . import fila
except ImportError:
    import fila


URL_INFERENCIA = os.getenv(
    "URL_INFERENCIA",
    "http://localhost:8001"
)

MAX_TENTATIVAS = 3
ESPERA_BASE_S = 0.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [worker] %(message)s"
)

log = logging.getLogger("worker")


def executar_inferencia(texto):
    """Solicita a classificacao de sentimento."""
    resposta = requests.post(
        f"{URL_INFERENCIA}/predict",
        json={"texto": texto},
        timeout=10
    )
    resposta.raise_for_status()
    return resposta.json()


def processar_tarefa(tarefa):
    """Executa a tarefa com ate tres tentativas."""
    ultimo_erro = None

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            return executar_inferencia(tarefa["texto"])
        except requests.RequestException as erro:
            ultimo_erro = erro

            log.warning(
                "Falha na tarefa %s, tentativa %s/%s",
                tarefa["id"],
                tentativa,
                MAX_TENTATIVAS
            )

            if tentativa < MAX_TENTATIVAS:
                time.sleep(ESPERA_BASE_S * tentativa)

    raise ultimo_erro


def tratar_tarefa(tarefa):
    """Registra sucesso ou encaminha falhas para descarte."""
    tarefa_id = tarefa["id"]

    fila.guardar_status(
        tarefa_id,
        {"status": "processando"}
    )

    try:
        resultado = processar_tarefa(tarefa)

    except Exception as erro:
        log.error("Tarefa %s falhou: %s", tarefa_id, erro)

        fila.enviar_para_descarte(tarefa, str(erro))

        fila.guardar_status(
            tarefa_id,
            {
                "status": "falhou",
                "erro": str(erro)
            }
        )
        return

    fila.guardar_status(
        tarefa_id,
        {
            "status": "concluido",
            "resultado": resultado
        }
    )

    log.info("Tarefa %s concluida", tarefa_id)


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
