import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from robo.paginacao import coletar_todas_paginas, nome_do_conjunto, url_da_pagina

URL = ("https://portaldatransparencia.gov.br/beneficios/bolsa-familia/sacado/resultado"
       "?paginacaoSimples=true&tamanhoPagina=10&offset=0&colunasSelecionadas=mesFolha%2Cvalor"
       "&beneficiario=1&t=TOKEN&_=123")
VALOR_FALSO_DO_PORTAL = 9223372036854775807  # recordsTotal quando há próxima página


def _portal_falso(total: int):
    chamadas: list[str] = []

    async def buscar(url: str) -> dict:
        chamadas.append(url)
        q = parse_qs(urlsplit(url).query)
        offset, tam = int(q["offset"][0]), int(q["tamanhoPagina"][0])
        dados = [{"n": i} for i in range(offset, min(offset + tam, total))]
        cheia = len(dados) == tam
        return {"data": dados, "recordsTotal": VALOR_FALSO_DO_PORTAL if cheia else offset + len(dados), "error": None}

    return buscar, chamadas


def test_url_da_pagina_troca_so_a_paginacao():
    q = parse_qs(urlsplit(url_da_pagina(URL, 400, 200)).query)
    assert q["offset"] == ["400"] and q["tamanhoPagina"] == ["200"]
    assert q["t"] == ["TOKEN"] and q["colunasSelecionadas"] == ["mesFolha,valor"]
    assert "_" not in q


@pytest.mark.parametrize("total, tamanho, paginas", [(81, 200, 1), (81, 10, 9), (80, 10, 9), (0, 10, 1)])
def test_coleta_ignora_records_total_e_para_na_pagina_incompleta(total, tamanho, paginas):
    buscar, chamadas = _portal_falso(total)
    registros, completa = asyncio.run(coletar_todas_paginas(buscar, URL, tamanho))
    assert [r["n"] for r in registros] == list(range(total))
    assert completa is True
    assert len(chamadas) == paginas


def test_coleta_marca_incompleta_no_limite_de_paginas():
    buscar, _ = _portal_falso(1000)
    registros, completa = asyncio.run(coletar_todas_paginas(buscar, URL, 10, max_paginas=3))
    assert len(registros) == 30 and completa is False


def test_coleta_propaga_erro_do_portal():
    async def buscar(url):
        return {"data": [], "error": "falhou"}

    with pytest.raises(RuntimeError, match="falhou"):
        asyncio.run(coletar_todas_paginas(buscar, URL, 10))


def test_nome_do_conjunto():
    assert nome_do_conjunto(URL) == "sacado"
    assert nome_do_conjunto("https://x/beneficios/auxilio-emergencial/recebido/resultado?a=1") == "recebido"
