"""Erros de domínio da consulta.

Cada erro carrega um ``codigo`` estável (para quem integra via API) e uma
``mensagem`` legível, que vai no JSON de saída.
"""

from __future__ import annotations

MSG_TEMPO_ESGOTADO = "Não foi possível retornar os dados no tempo de resposta solicitado"


class ErroConsulta(Exception):
    codigo = "erro_interno"

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class TermoInvalido(ErroConsulta):
    codigo = "termo_invalido"


class SemResultados(ErroConsulta):
    codigo = "sem_resultados"


class TempoEsgotado(ErroConsulta):
    codigo = "tempo_esgotado"

    def __init__(self, mensagem: str = MSG_TEMPO_ESGOTADO):
        super().__init__(mensagem)


class BloqueioAntiBot(ErroConsulta):
    """O portal respondeu com a verificação humana do AWS WAF (CAPTCHA).

    O robô não tenta resolver nem contornar a verificação: devolve este erro.
    """

    codigo = "bloqueio_anti_bot"

    def __init__(self, mensagem: str = (
        "O Portal da Transparência exigiu verificação humana (CAPTCHA do AWS WAF). "
        "O robô não contorna essa proteção; tente novamente mais tarde."
    )):
        super().__init__(mensagem)
