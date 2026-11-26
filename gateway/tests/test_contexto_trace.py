"""Revisao da isolacao e do ciclo de vida do contexto de rastreamento."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import rastreamento


def test_span_filho_restaura_pai_e_raiz_limpa_contexto():
    assert rastreamento.cabecalho() is None
    with rastreamento.span("teste", "pai"):
        pai = rastreamento.cabecalho()
        with rastreamento.span("teste", "filho"):
            filho = rastreamento.cabecalho()
            assert filho.split("-")[1] == pai.split("-")[1]
            assert filho.split("-")[2] != pai.split("-")[2]
        assert rastreamento.cabecalho() == pai
    assert rastreamento.cabecalho() is None


def test_excecao_registra_erro_sem_expor_mensagem_e_limpa_contexto(capsys):
    with pytest.raises(RuntimeError):
        with rastreamento.span("teste", "operacao"):
            raise RuntimeError("conteudo privado de teste")
    saida = capsys.readouterr().out
    evento = json.loads(saida)
    assert evento["resultado"] == "erro"
    assert "conteudo privado" not in saida
    assert rastreamento.cabecalho() is None


def test_threads_simultaneas_nao_compartilham_trace():
    barreira = threading.Barrier(2)
    def executar():
        assert rastreamento.cabecalho() is None
        with rastreamento.span("teste", "concorrente"):
            antes = rastreamento.cabecalho()
            barreira.wait(timeout=5)
            assert rastreamento.cabecalho() == antes
        assert rastreamento.cabecalho() is None
        return antes
    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = list(executor.map(lambda _: executar(), range(2)))
    assert a.split("-")[1] != b.split("-")[1]


@pytest.mark.parametrize("pai", [
    "00-" + "0" * 32 + "-123456789abcdef0-01",
    "00-123456789abcdef0123456789abcdef0-" + "0" * 16 + "-01",
    "ff-123456789abcdef0123456789abcdef0-123456789abcdef0-01",
    "00-123456789abcdef0123456789abcdef0-123456789abcdef0-01-extra",
])
def test_contexto_invalido_inicia_raiz_sem_pai(pai, capsys):
    with rastreamento.span("teste", "entrada", pai=pai):
        assert rastreamento.cabecalho() != pai
    evento = json.loads(capsys.readouterr().out)
    assert evento["parent_span_id"] is None
    assert int(evento["trace_id"], 16) != 0
