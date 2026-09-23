"""Portal da Transparência falso, servido pelo roteamento do Playwright.

Reproduz a estrutura que o robô usa no portal real (ids, classes, busca por XHR
em outro host, acordeão, tabelas alimentadas por endpoint paginado), com dados
fictícios. Permite testar o fluxo inteiro sem internet e sem o WAF do portal.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import BrowserContext, Route

BASE = "https://portal.teste"
BUSCA = "https://busca.portal.teste/busca/pessoa-fisica"
VALOR_FALSO = 9223372036854775807

PESSOAS = {
    "1-fulano-de-tal": {"nome": "FULANO DE TAL", "cpf": "***.111.222-**", "local": "CIDADE A - UF",
                        "beneficios": [("Bolsa Família", "/beneficios/bolsa-familia/11"),
                                       ("Auxílio Emergencial", "/beneficios/auxilio-emergencial/22")]},
    "2-ciclana-sobrenome": {"nome": "CICLANA SOBRENOME", "cpf": "***.333.444-**", "local": "CIDADE B - UF",
                            "beneficios": [("Auxílio Brasil", "/beneficios/auxilio-brasil/33")]},
    "3-beltrano-sobrenome": {"nome": "BELTRANO SOBRENOME", "cpf": "***.555.666-**", "local": "CIDADE C - UF",
                             "beneficios": []},
}

# Quantas parcelas cada conjunto de cada benefício tem.
PARCELAS = {
    "/beneficios/bolsa-familia/recebido/resultado": 23,
    "/beneficios/bolsa-familia/sacado/resultado": 7,
    "/beneficios/auxilio-emergencial/recebido/resultado": 14,
    "/beneficios/auxilio-brasil/sacado/resultado": 3,
}
TABELAS_DO_DETALHE = {
    "bolsa-familia": [("tabelaDetalheValoresRecebidos", "recebido"), ("tabelaDetalheValoresSacados", "sacado")],
    "auxilio-emergencial": [("tabelaDetalheDisponibilizado", "recebido")],
    "auxilio-brasil": [("tabelaDetalheValoresSacados", "sacado")],
}

VISAO_GERAL = f"""<!doctype html><html><head><title>Painel de Pessoa</title></head><body><main>
<div id="cookiebar"><button id="accept-minimal-btn" onclick="document.getElementById('cookiebar').remove()">Rejeitar cookies opcionais</button></div>
<a id="link-consulta-pessoa-fisica" href="/pessoa-fisica/busca/lista">Busca de Pessoa Física</a>
</main></body></html>"""

LISTA = f"""<!doctype html><html><head><title>Consulta de Pessoa Física</title></head><body><main>
<form id="form-busca">
  <input id="termo" name="termo" type="search">
  <button class="header" type="button" onclick="document.getElementById('filtros').style.display='block'">REFINE A BUSCA</button>
  <div id="filtros" style="display:none"><input id="beneficiarioProgramaSocial" type="checkbox" value="true"></div>
</form>
<p>Foram encontrados <strong id="countResultados"></strong> resultados <span id="infoTermo">para o termo <strong id="t"></strong></span></p>
<span id="resultados"></span>
<script>
document.getElementById('form-busca').addEventListener('submit', async (ev) => {{
  ev.preventDefault();
  const termo = document.getElementById('termo').value;
  const filtro = document.getElementById('beneficiarioProgramaSocial').checked;
  const url = '{BUSCA}?termo=' + encodeURIComponent(termo) + (filtro ? '&beneficiarioProgramaSocial=true' : '');
  const r = await (await fetch(url)).json();
  document.getElementById('countResultados').textContent = String(r.total);
  document.getElementById('t').textContent = termo;
  document.getElementById('resultados').innerHTML = r.itens.map(i =>
    '<div><a class="link-busca-nome" href="/busca/pessoa-fisica/' + i.id + '">' + i.nome + '</a></div>').join('');
}});
</script>
</main></body></html>"""


def _panorama(pessoa: dict) -> str:
    tabelas = "".join(
        f"""<strong>{programa}</strong><br><table><thead><tr><th>Detalhar</th><th>NIS</th><th>Nome</th><th>Valor Recebido</th></tr></thead>
        <tbody><tr><td><a class="br-button" href="{url}">Detalhar</a></td><td>1.234.567.890-1</td><td>{pessoa['nome']}</td><td>R$ 1.000,00</td></tr></tbody></table>"""
        for programa, url in pessoa["beneficios"]
    )
    return f"""<!doctype html><html><head><title>Pessoa Física</title></head><body><main>
<section class="dados-tabelados"><div class="row">
  <div><strong>Nome</strong> <span>{pessoa['nome']}</span></div>
  <div><strong>CPF</strong> <span>{pessoa['cpf']}</span></div>
  <div><strong>Localidade</strong> <span>{pessoa['local']}</span></div>
  <div><a href="#">Imprimir</a></div>
</div></section>
<div class="br-accordion">
  <div class="item"><button class="header" type="button" aria-controls="acc-rec"
     onclick="const c=document.getElementById('acc-rec'); c.style.display = c.style.display==='none' ? 'block' : 'none'">
     <span class="title">Recebimentos de recursos</span></button></div>
  <div id="acc-rec" style="display:none"><div class="responsive">{tabelas}</div></div>
</div>
</main></body></html>"""


def _detalhe(programa: str) -> str:
    tabelas = TABELAS_DO_DETALHE[programa]
    html_tabelas = "".join(f'<table id="{tid}"><thead><tr><th>Mês</th><th>Valor</th></tr></thead><tbody></tbody></table>'
                           for tid, _ in tabelas)
    chamadas = "".join(
        f"fetch('/beneficios/{programa}/{conjunto}/resultado?paginacaoSimples=true&tamanhoPagina=10&offset=0&t=TOKEN');"
        for _, conjunto in tabelas
    )
    return f"""<!doctype html><html><head><title>Detalhe</title></head><body><main>
<section class="dados-tabelados"><div class="row">
  <div><b>Nome</b> <span>BENEFICIARIO</span></div><div><b>NIS</b> 1.234.567.890-1</div>
</div></section>{html_tabelas}<script>{chamadas}</script></main></body></html>"""


PAGINA_DO_WAF = """<!doctype html><html><head><title>Human Verification</title></head>
<body><div id="captcha-container"></div><script>window.gokuProps = {};</script></body></html>"""


async def instalar(ctx: BrowserContext, *, waf: bool = False, busca_trava: bool = False) -> None:
    """Liga o portal falso no contexto. ``waf`` devolve o CAPTCHA; ``busca_trava`` derruba a busca."""

    async def html(route: Route, corpo: str, status: int = 200, headers: dict | None = None) -> None:
        await route.fulfill(status=status, body=corpo, content_type="text/html; charset=utf-8", headers=headers or {})

    async def portal(route: Route) -> None:
        caminho = urlsplit(route.request.url).path
        if waf:
            return await html(route, PAGINA_DO_WAF, 202, {"x-amzn-waf-action": "captcha"})
        if caminho == "/pessoa/visao-geral":
            return await html(route, VISAO_GERAL)
        if caminho == "/pessoa-fisica/busca/lista":
            return await html(route, LISTA)
        if caminho.startswith("/busca/pessoa-fisica/"):
            return await html(route, _panorama(PESSOAS[caminho.rsplit("/", 1)[1]]))
        if caminho in PARCELAS:
            q = parse_qs(urlsplit(route.request.url).query)
            offset, tam = int(q["offset"][0]), int(q["tamanhoPagina"][0])
            dados = [{"mes": f"{i + 1:02d}/2024", "valor": "100,00"} for i in range(offset, min(offset + tam, PARCELAS[caminho]))]
            total = VALOR_FALSO if len(dados) == tam else offset + len(dados)
            corpo = {"draw": 1, "recordsTotal": total, "recordsFiltered": total, "data": dados, "error": None}
            return await route.fulfill(status=200, body=json.dumps(corpo), content_type="application/json")
        if caminho.startswith("/beneficios/"):
            return await html(route, _detalhe(caminho.split("/")[2]))
        await route.fulfill(status=404, body="")

    async def busca(route: Route) -> None:
        if busca_trava:
            return await route.abort()
        q = parse_qs(urlsplit(route.request.url).query)
        termo = q["termo"][0].upper()
        filtro = q.get("beneficiarioProgramaSocial") == ["true"]
        if termo in ("FULANO DE TAL", "12345678909"):
            ids = ["1-fulano-de-tal"]
        elif termo == "SOBRENOME":
            # Sem filtro, o primeiro é quem não recebe benefício; com filtro, só quem recebe.
            ids = ["2-ciclana-sobrenome"] if filtro else ["3-beltrano-sobrenome", "2-ciclana-sobrenome"]
        else:
            ids = []
        corpo = {"total": len(ids), "itens": [{"id": i, "nome": PESSOAS[i]["nome"]} for i in ids]}
        await route.fulfill(status=200, body=json.dumps(corpo), content_type="application/json",
                            headers={"Access-Control-Allow-Origin": "*"})

    await ctx.route(f"{BASE}/**", portal)
    await ctx.route(f"{BUSCA}**", busca)
