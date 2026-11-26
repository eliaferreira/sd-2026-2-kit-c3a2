from unittest.mock import Mock, call

import pytest
import requests

from worker import main

TAREFA = {"id": "falha-teste", "texto": "texto privado"}


def erro_http(status):
    resposta = requests.Response()
    resposta.status_code = status
    return requests.HTTPError("corpo privado", response=resposta)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_tentativas_limitadas_com_backoff_exponencial(monkeypatch, status):
    executar = Mock(side_effect=erro_http(status))
    dormir = Mock()
    monkeypatch.setattr(main, "executar_inferencia", executar)
    monkeypatch.setattr(main.time, "sleep", dormir)
    monkeypatch.setattr(main, "MAX_TENTATIVAS", 4)
    with pytest.raises(requests.HTTPError):
        main.processar_tarefa(TAREFA)
    assert executar.call_count == 4
    assert dormir.call_args_list == [call(0.5), call(1.0), call(2.0)]


@pytest.mark.parametrize("status", [400, 401, 404, 422])
def test_erro_permanente_nao_retenta(monkeypatch, status):
    executar = Mock(side_effect=erro_http(status))
    monkeypatch.setattr(main, "executar_inferencia", executar)
    with pytest.raises(requests.HTTPError):
        main.processar_tarefa(TAREFA)
    assert executar.call_count == 1


def test_timeout_e_fechamento_da_resposta(monkeypatch):
    resposta = Mock(status_code=200)
    post = Mock(return_value=resposta)
    monkeypatch.setattr(main.requests, "post", post)
    monkeypatch.setattr(main, "TIMEOUT_S", 0.7)
    main.executar_inferencia("teste")
    assert post.call_args.kwargs["timeout"] == 0.7
    assert post.call_args.kwargs["allow_redirects"] is False
    resposta.close.assert_called_once()


def test_json_invalido_nao_retenta_e_vai_para_descarte_sem_dados(monkeypatch, caplog):
    resposta = Mock(status_code=200)
    resposta.json.side_effect = requests.exceptions.JSONDecodeError("privado", "texto privado", 0)
    post = Mock(return_value=resposta)
    status, descarte = Mock(), Mock()
    monkeypatch.setattr(main.requests, "post", post)
    monkeypatch.setattr(main.fila, "guardar_status", status)
    monkeypatch.setattr(main.fila, "enviar_para_descarte", descarte)
    main.tratar_tarefa(TAREFA)
    assert post.call_count == 1
    assert status.call_args.args[1]["status"] == "falhou"
    assert "privado" not in status.call_args.args[1]["erro"]
    assert "privado" not in descarte.call_args.args[1]
    assert "privado" not in caplog.text


def test_sucesso_apos_oscilacao_nao_vai_para_descarte(monkeypatch):
    executar = Mock(side_effect=[requests.Timeout(), {"sentimento": "positivo"}])
    status, descarte = Mock(), Mock()
    monkeypatch.setattr(main, "executar_inferencia", executar)
    monkeypatch.setattr(main.time, "sleep", Mock())
    monkeypatch.setattr(main.fila, "guardar_status", status)
    monkeypatch.setattr(main.fila, "enviar_para_descarte", descarte)
    main.tratar_tarefa(TAREFA)
    assert executar.call_count == 2
    assert status.call_args.args[1]["status"] == "concluido"
    descarte.assert_not_called()
