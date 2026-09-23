"""Classificação e normalização do termo de busca (nome, CPF ou NIS)."""

from __future__ import annotations

import re
from enum import Enum

from .erros import MSG_TEMPO_ESGOTADO, TermoInvalido

_SEPARADORES = re.compile(r"[.\-/\s]")


class TipoTermo(str, Enum):
    # CPF e NIS têm 11 dígitos: pelo número não dá para distinguir um do outro,
    # e o portal aceita os dois no mesmo campo.
    CPF_OU_NIS = "cpf_ou_nis"
    NOME = "nome"


def classificar_termo(termo: str) -> tuple[str, TipoTermo]:
    """Devolve o termo normalizado e o seu tipo; levanta TermoInvalido se não servir."""
    texto = " ".join((termo or "").split())
    if not texto:
        raise TermoInvalido("Informe um nome, CPF ou NIS.")

    digitos = _SEPARADORES.sub("", texto)
    if digitos.isdigit():
        if len(digitos) != 11:
            raise TermoInvalido("CPF e NIS devem ter 11 dígitos.")
        return digitos, TipoTermo.CPF_OU_NIS

    if not any(c.isalpha() for c in texto):
        raise TermoInvalido("O termo deve ser um nome, CPF ou NIS.")
    if any(c.isdigit() for c in texto):
        raise TermoInvalido("Nome não pode conter números.")
    return texto, TipoTermo.NOME


def mensagem_sem_resultados(tipo: TipoTermo, termo: str, texto_do_portal: str | None) -> str:
    """Mensagem de erro para uma busca sem resultados, conforme os cenários do desafio.

    - CPF/NIS inexistente: o portal só diz "0 resultados", mas o desafio pede a
      mensagem de tempo de resposta.
    - Nome inexistente: repassa a frase do próprio portal
      ("Foram encontrados 0 resultados para o termo ...").
    """
    if tipo is TipoTermo.CPF_OU_NIS:
        return MSG_TEMPO_ESGOTADO
    if texto_do_portal:
        return " ".join(texto_do_portal.split())
    return f"Foram encontrados 0 resultados para o termo {termo}"
