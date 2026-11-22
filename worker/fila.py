
"""
Gerenciamento da fila Redis - C3.A2.

Responsavel por publicar tarefas de inferencia,
consumir mensagens e acompanhar seu processamento.
"""

import json
import os
import uuid

import redis


REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0"
)

FILA_TAREFAS = "inferencia:tarefas"
FILA_DESCARTE = "inferencia:descarte"
PREFIXO_STATUS = "inferencia:status:"

VALIDADE_STATUS = 24 * 60 * 60


def conectar():
    """Cria uma conexao com o Redis."""
    return redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3
    )


def guardar_status(tarefa_id, dados):
    """Registra o status de uma tarefa."""
    conectar().set(
        PREFIXO_STATUS + tarefa_id,
        json.dumps(dados),
        ex=VALIDADE_STATUS
    )


def consultar_status(tarefa_id):
    """Consulta o status e o resultado da tarefa."""
    resultado = conectar().get(
        PREFIXO_STATUS + tarefa_id
    )

    if resultado is None:
        return None

    return json.loads(resultado)


def publicar_tarefa(texto):
    """Publica uma nova tarefa de inferencia."""
    tarefa_id = str(uuid.uuid4())

    tarefa = {
        "id": tarefa_id,
        "texto": texto
    }

    guardar_status(
        tarefa_id,
        {"status": "na_fila"}
    )

    conectar().rpush(
        FILA_TAREFAS,
        json.dumps(tarefa)
    )

    return tarefa_id


def consumir_tarefa(timeout=5):
    """Aguarda uma tarefa na fila Redis."""
    resultado = conectar().blpop(
        FILA_TAREFAS,
        timeout=timeout
    )

    if resultado is None:
        return None

    return json.loads(resultado[1])


def enviar_para_descarte(tarefa, erro):
    """Armazena tarefas que falharam."""
    dados = {
        **tarefa,
        "erro": str(erro)
    }

    conectar().rpush(
        FILA_DESCARTE,
        json.dumps(dados)
    )
