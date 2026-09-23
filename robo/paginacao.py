"""Coleta completa das tabelas paginadas (DataTables) das páginas de benefício.

As tabelas de detalhe são alimentadas por um endpoint ``.../resultado`` que
devolve ``{"data": [...], "recordsTotal": ...}``. Com ``paginacaoSimples=true``
(como o portal chama), ``recordsTotal`` vem como 9223372036854775807 sempre que
existe próxima página: o total só é real quando a página vem incompleta. Por isso
a coleta ignora ``recordsTotal`` e pagina até receber uma página menor que a pedida.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

BuscarJson = Callable[[str], Awaitable[dict[str, Any]]]

# Parâmetros que a coleta controla; "_" é o anti-cache do jQuery.
_CONTROLADOS = {"offset", "tamanhoPagina", "_"}


def url_da_pagina(url: str, offset: int, tamanho: int) -> str:
    partes = urlsplit(url)
    consulta = [(k, v) for k, v in parse_qsl(partes.query, keep_blank_values=True) if k not in _CONTROLADOS]
    consulta += [("tamanhoPagina", str(tamanho)), ("offset", str(offset))]
    return urlunsplit(partes._replace(query=urlencode(consulta)))


async def coletar_todas_paginas(
    buscar_json: BuscarJson,
    url: str,
    tamanho: int,
    max_paginas: int = 50,
) -> tuple[list[dict[str, Any]], bool]:
    """Devolve (registros, completa). ``completa`` é False se parou em ``max_paginas``."""
    registros: list[dict[str, Any]] = []
    for pagina in range(max_paginas):
        resposta = await buscar_json(url_da_pagina(url, pagina * tamanho, tamanho))
        if resposta.get("error"):
            raise RuntimeError(f"Portal devolveu erro na tabela: {resposta['error']}")
        dados = resposta.get("data") or []
        registros.extend(dados)
        if len(dados) < tamanho:
            return registros, True
    return registros, False


def nome_do_conjunto(url: str) -> str:
    """``/beneficios/bolsa-familia/sacado/resultado`` -> ``sacado``."""
    segmentos = [s for s in urlsplit(url).path.split("/") if s]
    if len(segmentos) >= 2 and segmentos[-1] == "resultado":
        return segmentos[-2]
    return segmentos[-1] if segmentos else url
