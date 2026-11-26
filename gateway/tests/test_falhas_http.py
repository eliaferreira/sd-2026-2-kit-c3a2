"""Falhas com conexoes TCP reais em loopback; nao usa servicos externos."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import app
from resiliencia import ClienteInferencia, Configuracao


@pytest.fixture
def servidor_inferencia(monkeypatch):
    estado = {"status": 200, "atraso": 0, "chamadas": 0, "falhas_iniciais": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            estado["chamadas"] += 1
            status = estado["status"]
            if estado["chamadas"] <= estado["falhas_iniciais"]:
                status = 503
            time.sleep(estado["atraso"])
            corpo = json.dumps({"sentimento": "positivo", "confianca": 0.91}).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # O cliente encerra a conexao ao atingir o timeout.

        def log_message(self, *_args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: servidor.serve_forever(poll_interval=0.01),
                              daemon=True)
    thread.start()
    monkeypatch.setattr(app, "URL_INFERENCIA", f"http://127.0.0.1:{servidor.server_port}")
    try:
        yield estado
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=3)


def test_http_real_retenta_503_e_recupera(client, auth, servidor_inferencia, monkeypatch):
    servidor_inferencia["falhas_iniciais"] = 2
    esperas = []
    monkeypatch.setattr(app, "cliente_inferencia",
                        ClienteInferencia(Configuracao(), dormir=esperas.append))
    resposta = client.post("/predict", json={"texto": "bom atendimento"}, headers=auth)
    assert resposta.status_code == 200
    assert servidor_inferencia["chamadas"] == 3
    assert esperas == [0.2, 0.4]


def test_http_real_lento_atinge_timeout(client, auth, servidor_inferencia, monkeypatch):
    servidor_inferencia["atraso"] = 0.2
    monkeypatch.setattr(app, "cliente_inferencia", ClienteInferencia(
        Configuracao(timeout_s=0.03, max_tentativas=2, backoff_s=0)))
    resposta = client.post("/predict", json={"texto": "teste"}, headers=auth)
    assert resposta.status_code == 503
    assert servidor_inferencia["chamadas"] == 2


def test_http_real_circuito_bloqueia_e_fecha_apos_retorno(
        client, auth, servidor_inferencia, monkeypatch):
    agora = [0.0]
    cliente = ClienteInferencia(Configuracao(max_tentativas=2, backoff_s=0,
                                            falhas_para_abrir=2),
                                relogio=lambda: agora[0])
    monkeypatch.setattr(app, "cliente_inferencia", cliente)
    servidor_inferencia["status"] = 503
    for _ in range(2):
        assert client.post("/predict", json={"texto": "teste"}, headers=auth).status_code == 503
    assert servidor_inferencia["chamadas"] == 4
    bloqueada = client.post("/predict", json={"texto": "teste"}, headers=auth)
    assert bloqueada.status_code == 503
    assert bloqueada.headers["Retry-After"] == "20"
    assert servidor_inferencia["chamadas"] == 4
    assert client.post("/predict", json={"texto": "teste"}).status_code == 401
    assert client.get("/saude").status_code == 200
    agora[0] += 20
    servidor_inferencia["status"] = 200
    assert client.post("/predict", json={"texto": "teste"}, headers=auth).status_code == 200
    assert servidor_inferencia["chamadas"] == 5
    assert cliente.circuito.estado == "fechado"
