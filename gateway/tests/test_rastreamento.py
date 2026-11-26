import json
from unittest.mock import MagicMock

import redis

import app

TRACE = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


def test_gateway_propaga_contexto_para_inferencia(client, auth, inferencia_falsa, capsys):
    resposta = client.post("/predict", json={"texto": "informacao privada"},
                           headers={**auth, "traceparent": TRACE})
    assert resposta.status_code == 200
    enviado = inferencia_falsa["chamadas"][0]["headers"]["traceparent"]
    assert enviado.split("-")[1] == TRACE.split("-")[1]
    spans = [json.loads(linha) for linha in capsys.readouterr().out.splitlines()
             if linha.startswith('{"tipo": "span"')]
    raiz = next(s for s in spans if s["nome"] == "HTTP POST")
    saida = next(s for s in spans if s["nome"] == "inferencia.predict")
    assert raiz["parent_span_id"] == TRACE.split("-")[2]
    assert saida["parent_span_id"] == raiz["span_id"]
    assert enviado.split("-")[2] == saida["span_id"]
    assert "informacao privada" not in json.dumps(spans)


def test_enfileira_com_trace_e_dono_em_transacao(client, auth, monkeypatch):
    conexao = MagicMock()
    pipeline = conexao.pipeline.return_value.__enter__.return_value
    monkeypatch.setattr(app.redis, "from_url", lambda *args, **kwargs: conexao)
    resposta = client.post("/tarefas", json={"texto": "privado"},
                           headers={**auth, "traceparent": TRACE})
    assert resposta.status_code == 202
    assert conexao.pipeline.call_args.kwargs["transaction"] is True
    tarefa = json.loads(pipeline.rpush.call_args.args[1])
    assert tarefa["traceparent"].split("-")[1] == TRACE.split("-")[1]
    assert tarefa["id"] == resposta.json()["id"]
    assert pipeline.set.call_args_list[1].args[1] == "usuario-teste"
    pipeline.execute.assert_called_once()


def test_tarefas_exige_token_e_trata_fila_indisponivel(client, auth, monkeypatch):
    assert client.post("/tarefas", json={"texto": "oi"}).status_code == 401
    def falhar(*args, **kwargs):
        raise redis.ConnectionError("segredo interno")
    monkeypatch.setattr(app.redis, "from_url", falhar)
    resposta = client.post("/tarefas", json={"texto": "oi"}, headers=auth)
    assert resposta.status_code == 503
    assert "segredo" not in resposta.text


def test_status_respeita_dono(client, auth, monkeypatch):
    conexao = MagicMock()
    monkeypatch.setattr(app.redis, "from_url", lambda *args, **kwargs: conexao)
    url = "/tarefas/00000000-0000-4000-8000-000000000001"
    conexao.get.return_value = "outro-usuario"
    assert client.get(url, headers=auth).status_code == 404
    conexao.get.side_effect = ["usuario-teste", '{"status":"concluido"}']
    assert client.get(url, headers=auth).json() == {"status": "concluido"}


def test_traceparent_invalido_cria_trace_novo(client, auth, inferencia_falsa):
    resposta = client.post("/predict", json={"texto": "oi"},
                           headers={**auth, "traceparent": "invalido"})
    assert resposta.status_code == 200
    assert len(resposta.headers["traceparent"].split("-")[1]) == 32
