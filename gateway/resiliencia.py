"""Protecao da chamada de classificacao, que nao altera dados na inferencia."""
import logging
import math
import os
import threading
import time
from dataclasses import dataclass

import requests
import rastreamento

log = logging.getLogger("gateway.resiliencia")
STATUS_TRANSITORIOS = {429, 500, 502, 503, 504}


class FalhaDependencia(Exception):
    """Erro seguro para converter em 503, sem corpo ou URL da dependencia."""


class CircuitoAberto(FalhaDependencia):
    def __init__(self, espera_s):
        super().__init__("circuito da inferencia aberto")
        self.espera_s = max(1, math.ceil(espera_s))


class RequisicaoRecusada(Exception):
    def __init__(self, status_code):
        super().__init__("requisicao recusada pela inferencia")
        self.status_code = status_code


@dataclass(frozen=True)
class Configuracao:
    timeout_s: float = 3.0
    max_tentativas: int = 3
    backoff_s: float = 0.2
    falhas_para_abrir: int = 3
    espera_circuito_s: float = 20.0

    def __post_init__(self):
        for nome in ("timeout_s", "backoff_s", "espera_circuito_s"):
            valor = getattr(self, nome)
            if not math.isfinite(valor) or valor < 0:
                raise ValueError(f"{nome} deve ser finito e nao negativo")
        if self.timeout_s == 0:
            raise ValueError("timeout_s deve ser positivo")
        for nome in ("max_tentativas", "falhas_para_abrir"):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                raise ValueError(f"{nome} deve ser inteiro positivo")

    @classmethod
    def do_ambiente(cls):
        return cls(
            timeout_s=float(os.getenv("INFERENCIA_TIMEOUT_S", "3")),
            max_tentativas=int(os.getenv("INFERENCIA_MAX_TENTATIVAS", "3")),
            backoff_s=float(os.getenv("INFERENCIA_BACKOFF_S", "0.2")),
            falhas_para_abrir=int(os.getenv("CIRCUITO_INFERENCIA_FALHAS", "3")),
            espera_circuito_s=float(os.getenv("CIRCUITO_INFERENCIA_ESPERA_S", "20")),
        )


class CircuitBreaker:
    """Conta operacoes esgotadas; permite uma unica sondagem apos a espera.

    O lock protege apenas o estado, nunca a rede ou o backoff. A geracao
    impede que chamadas antigas fechem um circuito que acabou de abrir.
    """

    def __init__(self, configuracao, relogio=time.monotonic):
        self.configuracao = configuracao
        self._relogio = relogio
        self._lock = threading.Lock()
        self._estado = "fechado"
        self._falhas = 0
        self._aberto_em = 0.0
        self._geracao = 0

    @property
    def estado(self):
        with self._lock:
            return self._estado

    def _admitir(self):
        with self._lock:
            if self._estado == "aberto":
                restante = self.configuracao.espera_circuito_s - (
                    self._relogio() - self._aberto_em
                )
                if restante > 0:
                    raise CircuitoAberto(restante)
                self._estado = "meio_aberto"
                log.info("dependencia=inferencia circuito=meio_aberto")
            elif self._estado == "meio_aberto":
                raise CircuitoAberto(1)
            return self._geracao

    def _concluir(self, geracao, sucesso):
        with self._lock:
            if geracao != self._geracao:
                return
            if sucesso:
                self._falhas = 0
                if self._estado == "meio_aberto":
                    self._estado = "fechado"
                    self._geracao += 1
                    log.info("dependencia=inferencia circuito=fechado")
                return
            self._falhas += 1
            if (self._estado == "meio_aberto"
                    or self._falhas >= self.configuracao.falhas_para_abrir):
                self._estado = "aberto"
                self._aberto_em = self._relogio()
                self._geracao += 1
                log.warning("dependencia=inferencia circuito=aberto")

    def executar(self, operacao):
        geracao = self._admitir()
        try:
            resultado = operacao()
        except RequisicaoRecusada:
            # Uma entrada invalida prova que a dependencia respondeu.
            self._concluir(geracao, sucesso=True)
            raise
        except Exception:
            self._concluir(geracao, sucesso=False)
            raise
        self._concluir(geracao, sucesso=True)
        return resultado


class ClienteInferencia:
    def __init__(self, configuracao, *, relogio=time.monotonic, dormir=time.sleep):
        self.configuracao = configuracao
        self.circuito = CircuitBreaker(configuracao, relogio)
        self._dormir = dormir

    def prever(self, url, entrada):
        return self.circuito.executar(lambda: self._com_tentativas(url, entrada))

    def _com_tentativas(self, url, entrada):
        cfg = self.configuracao
        for tentativa in range(1, cfg.max_tentativas + 1):
            motivo = "conexao"
            resposta = None
            try:
                resposta = requests.post(
                    f"{url.rstrip('/')}/predict", json=entrada,
                    timeout=cfg.timeout_s, allow_redirects=False,
                    headers={"traceparent": rastreamento.cabecalho()},
                )
                status = resposta.status_code
                if 400 <= status < 500 and status != 429:
                    raise RequisicaoRecusada(status)
                if status == 200:
                    return self._validar(resposta)
                if status not in STATUS_TRANSITORIOS:
                    raise FalhaDependencia("resposta HTTP inesperada")
                motivo = f"http_{status}"
            except (requests.ConnectionError, requests.Timeout) as erro:
                motivo = type(erro).__name__
            except requests.RequestException:
                raise FalhaDependencia("falha no protocolo HTTP") from None
            finally:
                if resposta is not None:
                    resposta.close()

            log.warning("dependencia=inferencia tentativa=%s/%s motivo=%s",
                        tentativa, cfg.max_tentativas, motivo)
            if tentativa < cfg.max_tentativas:
                self._dormir(cfg.backoff_s * 2 ** (tentativa - 1))
        raise FalhaDependencia("tentativas de inferencia esgotadas")

    @staticmethod
    def _validar(resposta):
        try:
            corpo = resposta.json()
        except ValueError:
            raise FalhaDependencia("JSON de inferencia invalido") from None
        if not isinstance(corpo, dict):
            raise FalhaDependencia("resposta de inferencia invalida")
        confianca = corpo.get("confianca")
        if (corpo.get("sentimento") not in ("positivo", "negativo")
                or isinstance(confianca, bool)
                or not isinstance(confianca, (int, float))
                or not 0 <= confianca <= 1 or not math.isfinite(confianca)):
            raise FalhaDependencia("resposta de inferencia invalida")
        return corpo
