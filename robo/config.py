"""Configuração do robô, lida de variáveis de ambiente (e de um .env opcional)."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv é conveniência, não requisito
    pass


def _bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _int(nome: str, padrao: int) -> int:
    valor = os.getenv(nome)
    return int(valor) if valor else padrao


def _float(nome: str, padrao: float) -> float:
    valor = os.getenv(nome)
    return float(valor) if valor else padrao


@dataclass(frozen=True)
class Config:
    url_base: str
    headless: bool
    # Tempo máximo de uma consulta inteira (busca + panorama + detalhes).
    timeout_consulta_s: float
    # Tempo máximo de cada ação isolada do Playwright (clique, espera, navegação).
    timeout_acao_ms: int
    # Quantas consultas podem usar o navegador ao mesmo tempo.
    max_simultaneas: int
    # Tamanho de página pedido às tabelas de detalhe dos benefícios.
    tamanho_pagina_detalhe: int
    # Quanto esperar a verificação silenciosa do WAF se resolver sozinha.
    espera_verificacao_s: float


def carregar_config() -> Config:
    return Config(
        url_base=os.getenv("PORTAL_URL_BASE", "https://portaldatransparencia.gov.br").rstrip("/"),
        headless=_bool("ROBO_HEADLESS", True),
        timeout_consulta_s=_float("ROBO_TIMEOUT_CONSULTA_S", 180.0),
        timeout_acao_ms=_int("ROBO_TIMEOUT_ACAO_MS", 30_000),
        max_simultaneas=_int("ROBO_MAX_SIMULTANEAS", 3),
        tamanho_pagina_detalhe=_int("ROBO_TAMANHO_PAGINA_DETALHE", 200),
        espera_verificacao_s=_float("ROBO_ESPERA_VERIFICACAO_S", 8.0),
    )
