"""Confere Qdrant real e os spans produzidos pela stack isolada do Compose."""
import json
import subprocess

import requests

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def executar(*argumentos):
    return subprocess.check_output(argumentos, text=True, encoding="utf-8")


def testar_qdrant():
    # O teste roda dentro do container de inferencia, na rede interna do Compose.
    codigo = r'''
import json
import urllib.request
base = "http://127.0.0.1:8001"
def chamada(metodo, caminho, dados=None):
    corpo = json.dumps(dados).encode() if dados is not None else None
    req = urllib.request.Request(base + caminho, data=corpo, method=metodo,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resposta:
        return json.load(resposta)
identificador = chamada("POST", "/documentos", {"texto": "documento teste vetorial"})["id"]
try:
    resultados = chamada("POST", "/buscar", {"texto": "documento teste vetorial", "k": 1})["resultados"]
    assert resultados and resultados[0]["id"] == identificador
finally:
    assert chamada("DELETE", "/documentos/" + identificador)["removido"] is True
print("Qdrant real: inserir, buscar e remover passaram")
'''
    print(executar("docker", "compose", "exec", "-T", "inferencia", "python", "-c", codigo))


def testar_spans():
    logs = executar("docker", "compose", "logs", "--no-color", "--no-log-prefix",
                    "gateway", "worker", "inferencia")
    spans = []
    for linha in logs.splitlines():
        try:
            item = json.loads(linha)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(item, dict) and item.get("trace_id") == TRACE_ID:
            spans.append(item)
    def encontrar(servico, nome):
        candidatos = [s for s in spans if s.get("servico") == servico and s.get("nome") == nome]
        assert len(candidatos) == 1, (servico, nome, candidatos)
        return candidatos[0]
    publicar = encontrar("gateway", "fila.publicar")
    processar = encontrar("worker", "fila.processar")
    chamar = encontrar("worker", "inferencia.predict")
    inferencia = encontrar("inferencia", "HTTP POST")
    assert processar["parent_span_id"] == publicar["span_id"]
    assert chamar["parent_span_id"] == processar["span_id"]
    assert inferencia["parent_span_id"] == chamar["span_id"]
    assert all(s["resultado"] == "ok" for s in (publicar, processar, chamar, inferencia))
    print("Trace real: gateway -> fila -> worker -> inferencia passou")


if __name__ == "__main__":
    testar_qdrant()
    testar_spans()
