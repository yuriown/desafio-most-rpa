"""Navegação e extração no Portal da Transparência.

Cada método é um passo do fluxo; a orquestração (ordem, tempo total, montagem do
JSON) fica em ``consulta.py``. Os trechos de JavaScript ficam em constantes para
poderem ser testados contra HTML de exemplo, sem acessar o portal.
"""

from __future__ import annotations

import base64
import logging
import re
import time
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, Response

from .config import Config
from .erros import BloqueioAntiBot, ErroConsulta
from .modelos import DetalheBeneficio, Pessoa, SecaoPanorama, Tabela, TabelaDetalhe
from .paginacao import coletar_todas_paginas, nome_do_conjunto

log = logging.getLogger(__name__)

# --- JavaScript de extração --------------------------------------------------

# Campos "rótulo: valor" do cabeçalho (Nome, CPF, Localidade, NIS...).
JS_CAMPOS = """
(seletor) => {
  const limpa = s => (s || '').replace(/\\s+/g, ' ').trim();
  const campos = {};
  const secao = document.querySelector(seletor);
  if (!secao) return campos;
  for (const bloco of secao.querySelectorAll('.row > div')) {
    const rotulo = bloco.querySelector('strong, b');
    if (!rotulo) continue;
    const chave = limpa(rotulo.textContent);
    const valor = limpa(bloco.textContent).slice(chave.length).trim();
    if (chave && valor) campos[chave] = valor;
  }
  return campos;
}
"""

# Seções do panorama (acordeões) e as tabelas dentro de cada uma. O conteúdo
# já vem no HTML mesmo com o acordeão fechado.
JS_SECOES_PANORAMA = """
() => {
  const limpa = s => (s || '').replace(/\\s+/g, ' ').trim();
  const lerTabelas = (raiz) => [...raiz.querySelectorAll('table')].map(tabela => {
    let rotulo = null;
    for (let el = tabela.previousElementSibling; el; el = el.previousElementSibling) {
      if (el.tagName === 'STRONG' || /^H[1-6]$/.test(el.tagName)) { rotulo = limpa(el.textContent); break; }
    }
    const colunas = [...tabela.querySelectorAll('thead th')].map(th => limpa(th.textContent));
    const linhas = [...tabela.querySelectorAll('tbody tr')].map(tr => {
      const linha = {};
      [...tr.children].forEach((celula, i) => {
        const coluna = colunas[i] || `coluna_${i + 1}`;
        const link = celula.querySelector('a[href]');
        if (coluna === 'Detalhar') {
          if (link) linha.detalhe_url = link.href;
          return;
        }
        linha[coluna] = limpa(celula.textContent);
      });
      return linha;
    }).filter(linha => Object.keys(linha).length > 0);
    return { rotulo, colunas: colunas.filter(c => c !== 'Detalhar'), linhas };
  });
  return [...document.querySelectorAll('.br-accordion .item')].map(item => {
    const botao = item.querySelector('button.header');
    const alvo = botao && botao.getAttribute('aria-controls');
    const conteudo = alvo && document.getElementById(alvo);
    return { titulo: limpa(item.querySelector('.title')?.textContent), tabelas: conteudo ? lerTabelas(conteudo) : [] };
  });
}
"""

# Tabelas lidas direto da tela; usado no detalhe quando não há XHR para capturar.
JS_TABELAS_DA_TELA = """
() => {
  const limpa = s => (s || '').replace(/\\s+/g, ' ').trim();
  return [...document.querySelectorAll('main table[id]')].map(tabela => {
    const colunas = [...tabela.querySelectorAll('thead th')].map(th => limpa(th.textContent));
    const registros = [...tabela.querySelectorAll('tbody tr')].map(tr => {
      const linha = {};
      [...tr.children].forEach((celula, i) => { linha[colunas[i] || `coluna_${i + 1}`] = limpa(celula.textContent); });
      return linha;
    });
    return { nome: tabela.id, registros };
  });
}
"""

# A lista de resultados terminou de desenhar (com zero ou mais resultados).
JS_BUSCA_RENDERIZADA = """
() => {
  const contagem = document.querySelector('#countResultados');
  if (!contagem) return false;
  const n = contagem.textContent.trim();
  if (!n) return false;
  return n === '0' || !!document.querySelector('#resultados a.link-busca-nome');
}
"""

# Zera a contagem antes de buscar, para não confundir o resultado anterior com o novo.
JS_LIMPAR_RESULTADOS = """
() => {
  const contagem = document.querySelector('#countResultados');
  if (contagem) contagem.textContent = '';
  const lista = document.querySelector('#resultados');
  if (lista) lista.innerHTML = '';
}
"""

JS_FETCH_JSON = """
async (url) => {
  const resposta = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' });
  if (!resposta.ok) throw new Error('HTTP ' + resposta.status + ' em ' + url);
  return await resposta.json();
}
"""

# Marcas da página de verificação humana do AWS WAF.
JS_EM_VERIFICACAO = """
() => document.title === 'Human Verification'
   || !!document.querySelector('#captcha-container, #challenge-container')
   || typeof window.gokuProps !== 'undefined'
"""


def _e_resposta_do_waf(resposta: Response | None) -> bool:
    return resposta is not None and "x-amzn-waf-action" in resposta.headers


def _e_a_busca_de_pessoas(resposta: Response) -> bool:
    partes = urlsplit(resposta.url)
    return partes.netloc.startswith("busca.") and partes.path == "/busca/pessoa-fisica"


class RoboPortal:
    """Passos da consulta, todos dentro de um mesmo ``BrowserContext``."""

    def __init__(self, contexto: BrowserContext, config: Config):
        self._ctx = contexto
        self._cfg = config
        self._pagina: Page | None = None

    @property
    def pagina(self) -> Page:
        if self._pagina is None:
            raise RuntimeError("abrir_busca() precisa ser chamado antes")
        return self._pagina

    # --- proteção anti-bot ----------------------------------------------------

    async def _em_verificacao(self, pagina: Page) -> bool:
        try:
            return await pagina.evaluate(JS_EM_VERIFICACAO)
        except Exception:
            # A página navegou no meio da avaliação: é a verificação se resolvendo.
            return True

    async def _aguardar_liberacao(self, pagina: Page) -> None:
        """Se o WAF interceptou, dá tempo para a verificação *silenciosa* terminar.

        A verificação silenciosa é resolvida pelo JavaScript da própria página,
        como em qualquer navegador. Se ela escalar para CAPTCHA, o robô desiste
        com BloqueioAntiBot: não resolve nem contorna o CAPTCHA.
        """
        if not await self._em_verificacao(pagina):
            return
        log.info("portal pediu verificação; aguardando até %.0fs", self._cfg.espera_verificacao_s)
        limite = time.monotonic() + self._cfg.espera_verificacao_s
        while time.monotonic() < limite:
            await pagina.wait_for_timeout(500)
            if not await self._em_verificacao(pagina):
                await pagina.wait_for_load_state("domcontentloaded")
                return
        raise BloqueioAntiBot()

    async def _ir_para(self, pagina: Page, url: str) -> None:
        resposta = await pagina.goto(url, wait_until="domcontentloaded")
        if resposta is not None and not resposta.ok and not _e_resposta_do_waf(resposta):
            raise ErroConsulta(f"O portal respondeu HTTP {resposta.status} em {url}")
        await self._aguardar_liberacao(pagina)

    async def _recusar_cookies_opcionais(self) -> None:
        # O banner de cookies cobre parte da tela (e da evidência). Escolhe a
        # opção mais restritiva: rejeitar os cookies opcionais.
        botao = self.pagina.locator("#accept-minimal-btn")
        try:
            if await botao.is_visible():
                await botao.click(timeout=3_000)
        except Exception:
            log.debug("banner de cookies não pôde ser fechado; seguindo")

    # --- passos do fluxo ------------------------------------------------------

    async def abrir_busca(self) -> None:
        """Passo 1: entra em "Pessoas Físicas e Jurídicas" e abre a busca de pessoa física."""
        self._pagina = await self._ctx.new_page()
        await self._ir_para(self.pagina, f"{self._cfg.url_base}/pessoa/visao-geral")
        await self._recusar_cookies_opcionais()
        await self.pagina.click("#link-consulta-pessoa-fisica")
        await self.pagina.wait_for_url("**/pessoa-fisica/busca/lista**", wait_until="domcontentloaded")
        await self._aguardar_liberacao(self.pagina)
        await self._recusar_cookies_opcionais()

    async def buscar(self, termo: str, filtro_programa_social: bool) -> int:
        """Passo 2: preenche o termo, aplica o filtro e busca. Devolve o total de resultados."""
        p = self.pagina
        await p.fill("#termo", termo)
        if filtro_programa_social:
            filtro = p.locator("#beneficiarioProgramaSocial")
            if not await filtro.is_visible():
                await p.locator("button.header", has_text=re.compile("refine a busca", re.I)).click()
            await filtro.check()

        await p.evaluate(JS_LIMPAR_RESULTADOS)
        async with p.expect_response(_e_a_busca_de_pessoas) as info:
            await p.press("#termo", "Enter")
        resposta = await info.value
        if _e_resposta_do_waf(resposta):
            raise BloqueioAntiBot()
        if not resposta.ok:
            raise ErroConsulta(f"A busca do portal respondeu HTTP {resposta.status}")

        await p.wait_for_function(JS_BUSCA_RENDERIZADA)
        contagem = await p.locator("#countResultados").inner_text()
        return int(re.sub(r"\D", "", contagem) or 0)

    async def texto_da_contagem(self) -> str | None:
        """A frase "Foram encontrados N resultados para o termo ..." como está na tela."""
        paragrafo = self.pagina.locator("p:has(#countResultados)")
        if await paragrafo.count() == 0:
            return None
        return await paragrafo.first.inner_text()

    async def abrir_primeiro_resultado(self) -> str:
        """Passo 3a: abre o primeiro registro da lista. Devolve a URL do panorama."""
        p = self.pagina
        await p.locator("#resultados a.link-busca-nome").first.click()
        await p.wait_for_url("**/busca/pessoa-fisica/**", wait_until="domcontentloaded")
        await self._aguardar_liberacao(p)
        await p.wait_for_selector("section.dados-tabelados")
        await self._recusar_cookies_opcionais()
        return p.url

    async def ler_panorama(self) -> tuple[Pessoa, list[SecaoPanorama]]:
        """Passo 3b: identificação da pessoa e seções do panorama."""
        p = self.pagina
        campos: dict[str, str] = await p.evaluate(JS_CAMPOS, "section.dados-tabelados")
        secoes = await p.evaluate(JS_SECOES_PANORAMA)
        pessoa = Pessoa(
            nome=campos.get("Nome"),
            cpf=campos.get("CPF"),
            localidade=campos.get("Localidade"),
            campos=campos,
        )
        return pessoa, [SecaoPanorama(titulo=s["titulo"], tabelas=[Tabela(**t) for t in s["tabelas"]]) for s in secoes]

    async def expandir_secoes(self) -> None:
        """Abre os acordeões, para que a evidência mostre os dados e não só os títulos."""
        p = self.pagina
        for botao in await p.locator(".br-accordion button.header").all():
            alvo = await botao.get_attribute("aria-controls")
            if alvo and not await p.locator(f"[id='{alvo}']").is_visible():
                await botao.click()
        await p.wait_for_timeout(300)

    async def capturar_tela(self, pagina: Page | None = None) -> str:
        """Passo 4: imagem da página inteira, em Base64."""
        png = await (pagina or self.pagina).screenshot(full_page=True, type="png")
        return base64.b64encode(png).decode("ascii")

    async def detalhar_beneficio(self, programa: str, url: str) -> DetalheBeneficio:
        """Passo 5: abre o detalhe do benefício e coleta todas as parcelas.

        As tabelas da tela mostram só 10 linhas por vez; o robô captura o
        endpoint JSON que as alimenta e pagina até o fim.
        """
        pagina = await self._ctx.new_page()
        endpoints: dict[str, str] = {}  # caminho -> primeira URL vista (com o token da sessão)

        def ao_responder(resposta: Response) -> None:
            caminho = urlsplit(resposta.url).path
            if caminho.endswith("/resultado") and resposta.request.resource_type in ("xhr", "fetch"):
                endpoints.setdefault(caminho, resposta.url)

        pagina.on("response", ao_responder)
        try:
            await self._ir_para(pagina, url)
            await pagina.wait_for_selector("section.dados-tabelados")
            identificacao: dict[str, str] = await pagina.evaluate(JS_CAMPOS, "section.dados-tabelados")

            # Espera cada tabela da tela pedir os seus dados.
            qtd_tabelas = await pagina.locator("main table[id^='tabela']").count()
            limite = time.monotonic() + self._cfg.timeout_acao_ms / 1000
            while len(endpoints) < qtd_tabelas and time.monotonic() < limite:
                await pagina.wait_for_timeout(250)

            tabelas: list[TabelaDetalhe] = []
            for caminho, url_xhr in endpoints.items():
                registros, completa = await coletar_todas_paginas(
                    lambda u: pagina.evaluate(JS_FETCH_JSON, u),
                    url_xhr,
                    self._cfg.tamanho_pagina_detalhe,
                )
                tabelas.append(TabelaDetalhe(
                    nome=nome_do_conjunto(url_xhr),
                    endpoint=caminho,
                    total_registros=len(registros),
                    completa=completa,
                    registros=registros,
                ))

            if not tabelas:
                # Sem XHR: tabela desenhada no servidor. Lê o que está na tela.
                for t in await pagina.evaluate(JS_TABELAS_DA_TELA):
                    tabelas.append(TabelaDetalhe(
                        nome=t["nome"], endpoint=urlsplit(url).path, total_registros=len(t["registros"]),
                        completa=True, registros=t["registros"],
                    ))

            return DetalheBeneficio(programa=programa, url=url, identificacao=identificacao, tabelas=tabelas)
        finally:
            await pagina.close()
