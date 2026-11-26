"""
Testes automatizados para os endpoints /saude e /predict do servico de inferencia.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

DIRETORIO_INFERENCIA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if DIRETORIO_INFERENCIA not in sys.path:
    sys.path.insert(0, DIRETORIO_INFERENCIA)

import treinar  # noqa: E402

# Garante que o modelo exista antes de importar o app nos testes
if not os.path.exists(treinar.config.obter_model_path()):
    treinar.treinar_e_salvar()

import app as app_modulo  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app_modulo.app)


def test_saude_retorna_200(client):
    resposta = client.get("/saude")
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["status"] == "ok"


def test_predict_retorna_formato_esperado(client):
    resposta = client.post("/predict", json={"texto": "o atendimento foi excelente e muito rapido"})
    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["sentimento"] in ("positivo", "negativo")
    assert dados["sentimento"] == "positivo"
    assert isinstance(dados["confianca"], float)
    assert 0.0 <= dados["confianca"] <= 1.0
    assert "tempo_ms" in dados


@pytest.mark.parametrize("payload", [{"texto": ""}, {"texto": "   "}, {}])
def test_predict_texto_vazio_ou_ausente_retorna_422(client, payload):
    resposta = client.post("/predict", json=payload)
    assert resposta.status_code == 422


def test_log_nao_expoe_conteudo_do_texto(client, capsys):
    segredo = "cpf-sensivel-99988877766"
    resposta = client.post("/predict", json={"texto": f"atendimento excelente {segredo}"})
    assert resposta.status_code == 200
    saida = capsys.readouterr().out
    assert "POST /predict -> 200" in saida
    assert segredo not in saida


def test_propaga_cabecalho_traceparent(client):
    trace = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    resposta = client.get("/saude", headers={"traceparent": trace})
    assert resposta.status_code == 200
    assert resposta.headers.get("traceparent") == trace


def test_trace_de_inferencia_vincula_span_ao_pai(client, capsys):
    import json
    trace = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    resposta = client.post("/predict", json={"texto": "conteudo privado"},
                           headers={"traceparent": trace})
    assert resposta.status_code == 200
    spans = [json.loads(linha) for linha in capsys.readouterr().out.splitlines()
             if linha.startswith('{"tipo": "span"')]
    assert spans[0]["trace_id"] == trace.split("-")[1]
    assert spans[0]["parent_span_id"] == trace.split("-")[2]
    assert "conteudo privado" not in json.dumps(spans)


def test_erro_inesperado_retorna_json_padronizado_sem_stacktrace(client, monkeypatch):
    def falhar(_texto: str):
        raise RuntimeError("detalhe interno sensivel")

    monkeypatch.setattr(app_modulo.modelo, "prever", falhar)
    resposta = client.post("/predict", json={"texto": "qualquer texto valido"})
    assert resposta.status_code == 500
    assert resposta.json() == {"detail": "erro interno no servico de inferencia"}
