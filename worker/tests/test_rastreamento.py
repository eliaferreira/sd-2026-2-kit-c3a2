import json
from unittest.mock import Mock

from worker import main


def test_worker_restaura_trace_da_mensagem(monkeypatch, capsys):
    enviado = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    resposta = Mock()
    resposta.json.return_value = {"sentimento": "positivo"}
    post = Mock(return_value=resposta)
    monkeypatch.setattr(main.requests, "post", post)
    monkeypatch.setattr(main.fila, "guardar_status", Mock())
    main.tratar_tarefa({"id": "abc", "texto": "privado", "traceparent": enviado})
    proximo = post.call_args.kwargs["headers"]["traceparent"]
    assert proximo.split("-")[1] == enviado.split("-")[1]
    spans = [json.loads(linha) for linha in capsys.readouterr().out.splitlines()
             if linha.startswith('{"tipo": "span"')]
    processo = next(s for s in spans if s["nome"] == "fila.processar")
    saida = next(s for s in spans if s["nome"] == "inferencia.predict")
    assert processo["parent_span_id"] == enviado.split("-")[2]
    assert saida["parent_span_id"] == processo["span_id"]
    assert proximo.split("-")[2] == saida["span_id"]
    assert "privado" not in json.dumps(spans)
