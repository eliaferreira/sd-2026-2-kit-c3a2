"""Falhas controladas e concorrencia, sem Redis, Qdrant ou nuvem."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests

import app
from conftest import RespostaFalsa
from resiliencia import (
    CircuitBreaker, CircuitoAberto, ClienteInferencia, Configuracao,
    FalhaDependencia, RequisicaoRecusada,
)

SUCESSO = {"sentimento": "positivo", "confianca": 0.91}


def falhar():
    raise FalhaDependencia("falha simulada")


@pytest.mark.parametrize("erro", [requests.ConnectionError, requests.Timeout])
def test_retenta_falhas_de_rede_com_backoff_exponencial(monkeypatch, erro):
    post = Mock(side_effect=[erro("dado privado"), erro(), RespostaFalsa(200, SUCESSO)])
    monkeypatch.setattr(requests, "post", post)
    dormir = Mock()
    cliente = ClienteInferencia(Configuracao(timeout_s=0.3), dormir=dormir)
    assert cliente.prever("http://interno", {"texto": "ok"}) == SUCESSO
    assert post.call_count == 3
    assert [chamada.args[0] for chamada in dormir.call_args_list] == [0.2, 0.4]
    assert all(c.kwargs["timeout"] == 0.3 for c in post.call_args_list)
    assert all(c.kwargs["allow_redirects"] is False for c in post.call_args_list)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_http_transitorio_retenta_e_fecha_respostas(monkeypatch, status):
    resposta = Mock(status_code=status)
    post = Mock(return_value=resposta)
    monkeypatch.setattr(requests, "post", post)
    cliente = ClienteInferencia(Configuracao(backoff_s=0))
    with pytest.raises(FalhaDependencia):
        cliente.prever("http://interno", {})
    assert post.call_count == 3
    assert resposta.close.call_count == 3
    # Tres tentativas contam como UMA operacao falha.
    assert cliente.circuito.estado == "fechado"


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_4xx_nao_retenta_nem_abre_circuito(client, auth, inferencia_falsa, status):
    inferencia_falsa["resposta"] = RespostaFalsa(status, {"detail": "privado"})
    for _ in range(4):
        resposta = client.post("/predict", json={"texto": "ok"}, headers=auth)
        assert resposta.status_code == status
        assert "privado" not in resposta.text
    assert len(inferencia_falsa["chamadas"]) == 4
    assert app.cliente_inferencia.circuito.estado == "fechado"


def test_abre_rejeita_sem_rede_e_recupera(client, auth, inferencia_falsa, monkeypatch):
    agora = [100.0]
    cliente = ClienteInferencia(Configuracao(backoff_s=0), relogio=lambda: agora[0])
    monkeypatch.setattr(app, "cliente_inferencia", cliente)
    inferencia_falsa["erro"] = requests.ConnectionError("texto e segredo internos")
    for _ in range(3):
        resposta = client.post("/predict", json={"texto": "ok"}, headers=auth)
        assert resposta.status_code == 503
        assert resposta.json() == {"detail": "servico de inferencia indisponivel"}
    assert len(inferencia_falsa["chamadas"]) == 9
    resposta = client.post("/predict", json={"texto": "ok"}, headers=auth)
    assert resposta.status_code == 503
    assert resposta.headers["Retry-After"] == "20"
    assert len(inferencia_falsa["chamadas"]) == 9
    assert client.get("/saude").json() == {"status": "ok"}
    inferencia_falsa["erro"] = None
    agora[0] += 20
    assert client.post("/predict", json={"texto": "ok"}, headers=auth).status_code == 200
    assert len(inferencia_falsa["chamadas"]) == 10
    assert cliente.circuito.estado == "fechado"


@pytest.mark.parametrize("corpo", [[], {}, {"sentimento": "neutro", "confianca": 0.9},
                                 {"sentimento": "positivo", "confianca": True},
                                 {"sentimento": "positivo", "confianca": float("nan")},
                                 {"sentimento": "positivo", "confianca": 1.1}])
def test_contrato_invalido_retorna_503_sem_retry(client, auth, inferencia_falsa, corpo):
    inferencia_falsa["resposta"] = RespostaFalsa(200, corpo)
    assert client.post("/predict", json={"texto": "ok"}, headers=auth).status_code == 503
    assert len(inferencia_falsa["chamadas"]) == 1


def test_json_invalido_e_logs_sem_conteudo(client, auth, monkeypatch, caplog):
    resposta = Mock(status_code=200)
    resposta.json.side_effect = ValueError("CPF segredo privado")
    post = Mock(return_value=resposta)
    monkeypatch.setattr(requests, "post", post)
    assert client.post("/predict", json={"texto": "CPF segredo privado"},
                       headers=auth).status_code == 503
    assert post.call_count == 1
    resposta.close.assert_called_once()
    assert "segredo privado" not in caplog.text


@pytest.mark.parametrize("status", [201, 302, 501])
def test_status_inesperado_falha_sem_retry(monkeypatch, status):
    post = Mock(return_value=RespostaFalsa(status))
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(FalhaDependencia):
        ClienteInferencia(Configuracao()).prever("http://interno", {})
    assert post.call_count == 1


def test_sucesso_zera_falhas_e_sondagem_falha_reabre():
    agora = [0.0]
    circuito = CircuitBreaker(Configuracao(falhas_para_abrir=2), lambda: agora[0])
    with pytest.raises(FalhaDependencia):
        circuito.executar(falhar)
    circuito.executar(lambda: "ok")
    with pytest.raises(FalhaDependencia):
        circuito.executar(falhar)
    assert circuito.estado == "fechado"
    with pytest.raises(FalhaDependencia):
        circuito.executar(falhar)
    agora[0] = 20
    with pytest.raises(FalhaDependencia):
        circuito.executar(falhar)
    with pytest.raises(CircuitoAberto) as erro:
        circuito.executar(lambda: "nao deve executar")
    assert erro.value.espera_s == 20
    agora[0] = 40
    # Entrada recusada nao e indisponibilidade: fecha a sondagem.
    def recusar():
        raise RequisicaoRecusada(422)
    with pytest.raises(RequisicaoRecusada):
        circuito.executar(recusar)
    assert circuito.estado == "fechado"


def test_apenas_uma_sondagem_concorrente():
    agora = [0.0]
    circuito = CircuitBreaker(Configuracao(falhas_para_abrir=1), lambda: agora[0])
    with pytest.raises(FalhaDependencia):
        circuito.executar(falhar)
    agora[0] = 20
    entrou, liberar = threading.Event(), threading.Event()
    def sondar():
        entrou.set()
        assert liberar.wait(3)
        return "recuperado"
    with ThreadPoolExecutor(max_workers=1) as executor:
        futuro = executor.submit(circuito.executar, sondar)
        try:
            assert entrou.wait(3)
            with pytest.raises(CircuitoAberto):
                circuito.executar(lambda: "nao deve entrar")
        finally:
            liberar.set()
        assert futuro.result(timeout=3) == "recuperado"
    assert circuito.estado == "fechado"


def test_sucesso_antigo_nao_fecha_circuito_aberto():
    circuito = CircuitBreaker(Configuracao(falhas_para_abrir=1))
    entrou, liberar = threading.Event(), threading.Event()
    def lento():
        entrou.set()
        assert liberar.wait(3)
    with ThreadPoolExecutor(max_workers=1) as executor:
        futuro = executor.submit(circuito.executar, lento)
        try:
            assert entrou.wait(3)
            with pytest.raises(FalhaDependencia):
                circuito.executar(falhar)
        finally:
            liberar.set()
        futuro.result(timeout=3)
    assert circuito.estado == "aberto"


@pytest.mark.parametrize("config", [dict(timeout_s=0), dict(timeout_s=float("inf")),
                                   dict(backoff_s=-1), dict(espera_circuito_s=-1),
                                   dict(max_tentativas=0), dict(falhas_para_abrir=0)])
def test_configuracao_invalida_falha_ao_iniciar(config):
    with pytest.raises(ValueError):
        Configuracao(**config)


def test_configuracao_por_ambiente(monkeypatch):
    for nome, valor in {"INFERENCIA_TIMEOUT_S": "1.5", "INFERENCIA_MAX_TENTATIVAS": "2",
                        "INFERENCIA_BACKOFF_S": "0.1", "CIRCUITO_INFERENCIA_FALHAS": "4",
                        "CIRCUITO_INFERENCIA_ESPERA_S": "8"}.items():
        monkeypatch.setenv(nome, valor)
    assert Configuracao.do_ambiente() == Configuracao(1.5, 2, 0.1, 4, 8)
