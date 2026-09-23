"""Orquestração de uma consulta: fluxo, tempo limite, erros e montagem do JSON."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.async_api import Error as ErroPlaywright
from playwright.async_api import TimeoutError as TempoPlaywright

from .config import Config
from .erros import ErroConsulta, SemResultados, TempoEsgotado
from .modelos import (
    ConsultaEntrada,
    DetalheBeneficio,
    Evidencia,
    Parametros,
    Pessoa,
    ResultadoConsulta,
    SecaoPanorama,
)
from .navegador import GerenciadorNavegador
from .portal import RoboPortal
from .termo import TipoTermo, classificar_termo, mensagem_sem_resultados

log = logging.getLogger(__name__)
FUSO = ZoneInfo("America/Sao_Paulo")


@dataclass
class _Coletado:
    """O que já foi coletado; sobrevive a um erro no meio do caminho."""

    total_resultados: int | None = None
    url_pessoa: str | None = None
    pessoa: Pessoa | None = None
    panorama: list[SecaoPanorama] = field(default_factory=list)
    beneficios: list[DetalheBeneficio] = field(default_factory=list)
    evidencia: Evidencia | None = None


def beneficios_a_detalhar(panorama: list[SecaoPanorama]) -> list[tuple[str, str]]:
    """(programa, url) de cada link "Detalhar" que leva a um benefício, sem repetir."""
    vistos: set[str] = set()
    saida: list[tuple[str, str]] = []
    for secao in panorama:
        for tabela in secao.tabelas:
            for linha in tabela.linhas:
                url = linha.get("detalhe_url")
                if not url or url in vistos or not urlsplit(url).path.startswith("/beneficios/"):
                    continue
                vistos.add(url)
                saida.append((tabela.rotulo or "Benefício", url))
    return saida


async def _fluxo(robo: RoboPortal, termo: str, tipo: TipoTermo, filtro: bool, coletado: _Coletado) -> None:
    await robo.abrir_busca()

    coletado.total_resultados = await robo.buscar(termo, filtro)
    if coletado.total_resultados == 0:
        coletado.evidencia = Evidencia(tela="resultado da busca", base64=await robo.capturar_tela())
        raise SemResultados(mensagem_sem_resultados(tipo, termo, await robo.texto_da_contagem()))

    coletado.url_pessoa = await robo.abrir_primeiro_resultado()
    coletado.pessoa, coletado.panorama = await robo.ler_panorama()

    await robo.expandir_secoes()
    coletado.evidencia = Evidencia(tela="panorama da pessoa", base64=await robo.capturar_tela())

    for programa, url in beneficios_a_detalhar(coletado.panorama):
        try:
            coletado.beneficios.append(await robo.detalhar_beneficio(programa, url))
        except (ErroConsulta, ErroPlaywright) as erro:
            # Um detalhe que falha não derruba a consulta inteira: fica registrado nele.
            mensagem = getattr(erro, "mensagem", None) or str(erro).splitlines()[0]
            log.warning("detalhe de %s falhou: %s", programa, mensagem)
            coletado.beneficios.append(DetalheBeneficio(programa=programa, url=url, erro=mensagem))


async def executar_consulta(
    gerenciador: GerenciadorNavegador,
    config: Config,
    entrada: ConsultaEntrada,
) -> ResultadoConsulta:
    id_consulta = uuid.uuid4().hex
    inicio = datetime.now(FUSO)
    t0 = time.perf_counter()
    parametros = Parametros(
        termo=entrada.termo,
        filtro_beneficiario_programa_social=entrada.filtro_beneficiario_programa_social,
    )
    coletado = _Coletado()
    erro: ErroConsulta | None = None

    try:
        termo, tipo = classificar_termo(entrada.termo)
        parametros.tipo_termo = tipo.value
        log.info("[%s] consulta %s (%s)", id_consulta, termo if tipo is TipoTermo.NOME else "***", tipo.value)

        # O tempo limite conta a partir do momento em que a consulta ganha um
        # contexto do navegador; a espera na fila do semáforo não entra.
        async with gerenciador.contexto() as ctx:
            robo = RoboPortal(ctx, config)
            try:
                await asyncio.wait_for(
                    _fluxo(robo, termo, tipo, entrada.filtro_beneficiario_programa_social, coletado),
                    timeout=config.timeout_consulta_s,
                )
            except ErroConsulta as e:
                erro = e
            except (TimeoutError, TempoPlaywright):
                erro = TempoEsgotado()
            except ErroPlaywright as e:
                log.exception("[%s] falha do navegador", id_consulta)
                erro = ErroConsulta(f"Falha na automação do navegador: {str(e).splitlines()[0]}")

            if erro is not None and coletado.evidencia is None:
                coletado.evidencia = await _evidencia_do_erro(robo)
    except ErroConsulta as e:  # termo inválido: nem chega a abrir o navegador
        erro = e

    if erro is not None:
        log.info("[%s] terminou com erro %s: %s", id_consulta, erro.codigo, erro.mensagem)

    return ResultadoConsulta(
        id_consulta=id_consulta,
        status="erro" if erro else "sucesso",
        data_hora_consulta=inicio,
        duracao_segundos=round(time.perf_counter() - t0, 2),
        parametros=parametros,
        codigo_erro=erro.codigo if erro else None,
        mensagem=erro.mensagem if erro else None,
        total_resultados_busca=coletado.total_resultados,
        url_pessoa=coletado.url_pessoa,
        pessoa=coletado.pessoa,
        panorama=coletado.panorama,
        beneficios=coletado.beneficios,
        evidencia=coletado.evidencia,
    )


async def _evidencia_do_erro(robo: RoboPortal) -> Evidencia | None:
    """Tenta registrar a tela em que o erro aconteceu; se não der, segue sem."""
    try:
        return Evidencia(tela="tela no momento do erro", base64=await asyncio.wait_for(robo.capturar_tela(), 15))
    except Exception:
        return None
