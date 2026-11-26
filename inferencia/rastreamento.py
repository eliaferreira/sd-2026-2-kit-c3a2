"""Rastreamento W3C minimo com spans em logs JSON, sem dados do usuario."""
import json
import re
import secrets
import time
from contextvars import ContextVar
from contextlib import contextmanager

_atual = ContextVar("trace_atual", default=None)
_PADRAO = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


def _parse(valor):
    match = _PADRAO.fullmatch(valor or "")
    if not match or int(match[1], 16) == 0 or int(match[2], 16) == 0:
        return None
    return match.groups()


def cabecalho():
    atual = _atual.get()
    return f"00-{atual[0]}-{atual[1]}-{atual[2]}" if atual else None


@contextmanager
def span(servico, nome, pai=None):
    recebido = _parse(pai if pai is not None else cabecalho())
    trace_id, parent_id, flags = recebido if recebido else (secrets.token_hex(16), None, "01")
    span_id = secrets.token_hex(8)
    token = _atual.set((trace_id, span_id, flags))
    inicio = time.monotonic()
    estado = {"resultado": "ok"}
    try:
        yield estado
    except BaseException:
        estado["resultado"] = "erro"
        raise
    finally:
        print(json.dumps({"tipo": "span", "servico": servico, "nome": nome,
                          "trace_id": trace_id, "span_id": span_id,
                          "parent_span_id": parent_id, "resultado": estado["resultado"],
                          "duracao_ms": round((time.monotonic() - inicio) * 1000, 2)}), flush=True)
        _atual.reset(token)
