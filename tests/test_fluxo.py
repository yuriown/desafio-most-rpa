"""Fluxo completo do robô contra o portal falso (ver portal_falso.py).

Cobre os cenários da seção 5 do desafio, o bloqueio anti-bot e a execução simultânea.
"""

import asyncio
import base64
import functools

import pytest
from playwright.async_api import Error as ErroPlaywright

from robo import ConsultaEntrada, GerenciadorNavegador, executar_consulta
from robo.config import Config
from robo.erros import MSG_TEMPO_ESGOTADO

from . import portal_falso

CONFIG = Config(
    url_base=portal_falso.BASE,
    headless=True,
    timeout_consulta_s=60,
    timeout_acao_ms=5_000,
    max_simultaneas=3,
    tamanho_pagina_detalhe=10,  # pequeno de propósito: força a paginação
    espera_verificacao_s=1,
)
PNG = b"\x89PNG\r\n\x1a\n"


def consultar(termo: str, filtro: bool = False, config: Config = CONFIG, **portal):
    async def rodar():
        gerenciador = GerenciadorNavegador(config, functools.partial(portal_falso.instalar, **portal))
        try:
            return await executar_consulta(gerenciador, config, ConsultaEntrada(
                termo=termo, filtro_beneficiario_programa_social=filtro))
        finally:
            await gerenciador.encerrar()

    return asyncio.run(rodar())


def test_sucesso_por_cpf():
    r = consultar("123.456.789-09")
    assert r.status == "sucesso", r.mensagem
    assert r.parametros.tipo_termo == "cpf_ou_nis"
    assert r.pessoa.nome == "FULANO DE TAL" and r.pessoa.cpf == "***.111.222-**"
    assert r.pessoa.localidade == "CIDADE A - UF"
    assert base64.b64decode(r.evidencia.base64).startswith(PNG)
    assert r.evidencia.tela == "panorama da pessoa"


def test_sucesso_por_nome_coleta_panorama_e_todos_os_detalhes():
    r = consultar("fulano de tal")
    assert r.status == "sucesso", r.mensagem
    [secao] = r.panorama
    assert secao.titulo == "Recebimentos de recursos"
    assert [t.rotulo for t in secao.tabelas] == ["Bolsa Família", "Auxílio Emergencial"]
    assert secao.tabelas[0].colunas == ["NIS", "Nome", "Valor Recebido"]

    por_programa = {b.programa: b for b in r.beneficios}
    assert set(por_programa) == {"Bolsa Família", "Auxílio Emergencial"}
    bolsa = por_programa["Bolsa Família"]
    assert bolsa.erro is None
    assert bolsa.identificacao == {"Nome": "BENEFICIARIO", "NIS": "1.234.567.890-1"}
    # 23 e 7 parcelas com página de 10: só sai certo se a paginação ignorar o recordsTotal falso.
    assert {t.nome: t.total_registros for t in bolsa.tabelas} == {"recebido": 23, "sacado": 7}
    assert all(t.completa for t in bolsa.tabelas)
    assert por_programa["Auxílio Emergencial"].tabelas[0].total_registros == 14


def test_erro_cpf_inexistente():
    r = consultar("98765432100")
    assert r.status == "erro"
    assert r.codigo_erro == "sem_resultados"
    assert r.mensagem == MSG_TEMPO_ESGOTADO
    assert r.evidencia is not None


def test_erro_nome_inexistente():
    r = consultar("NOME QUE NAO EXISTE")
    assert r.status == "erro"
    assert r.mensagem == "Foram encontrados 0 resultados para o termo NOME QUE NAO EXISTE"


def test_filtro_social_muda_o_primeiro_registro():
    sem_filtro = consultar("SOBRENOME")
    com_filtro = consultar("SOBRENOME", filtro=True)
    assert sem_filtro.pessoa.nome == "BELTRANO SOBRENOME"
    assert com_filtro.status == "sucesso"
    assert com_filtro.pessoa.nome == "CICLANA SOBRENOME"
    assert [b.programa for b in com_filtro.beneficios] == ["Auxílio Brasil"]


def test_captcha_vira_erro_de_bloqueio_sem_travar():
    r = consultar("FULANO DE TAL", waf=True)
    assert r.status == "erro"
    assert r.codigo_erro == "bloqueio_anti_bot"
    assert r.duracao_segundos < 20


def test_busca_que_nao_responde_vira_tempo_esgotado():
    config = Config(**{**CONFIG.__dict__, "timeout_acao_ms": 1_500})
    r = consultar("FULANO DE TAL", config=config, busca_trava=True)
    assert r.status == "erro"
    assert r.codigo_erro == "tempo_esgotado"
    assert r.mensagem == MSG_TEMPO_ESGOTADO


def test_navegador_nao_instalado_vira_json_de_erro(monkeypatch):
    # O erro que o Playwright dá quando o Chromium não foi baixado nesta máquina.
    async def sem_navegador(self):
        raise ErroPlaywright("BrowserType.launch: Executable doesn't exist at C:\\x\\chrome-headless-shell.exe")

    monkeypatch.setattr(GerenciadorNavegador, "_garantir_navegador", sem_navegador)
    r = consultar("FULANO DE TAL")
    assert r.status == "erro"
    assert r.codigo_erro == "navegador_indisponivel"
    assert "playwright install chromium" in r.mensagem


def test_termo_invalido_nem_abre_navegador():
    r = consultar("123")
    assert r.status == "erro" and r.codigo_erro == "termo_invalido"
    assert r.evidencia is None


def test_consultas_simultaneas_nao_se_misturam():
    async def rodar():
        gerenciador = GerenciadorNavegador(CONFIG, portal_falso.instalar)
        try:
            return await asyncio.gather(*(
                executar_consulta(gerenciador, CONFIG, ConsultaEntrada(termo=t, filtro_beneficiario_programa_social=f))
                for t, f in [("FULANO DE TAL", False), ("SOBRENOME", True), ("NINGUEM AQUI", False),
                             ("12345678909", False)]
            ))
        finally:
            await gerenciador.encerrar()

    resultados = asyncio.run(rodar())
    assert [r.pessoa.nome if r.pessoa else r.codigo_erro for r in resultados] == [
        "FULANO DE TAL", "CICLANA SOBRENOME", "sem_resultados", "FULANO DE TAL"]
    assert len({r.id_consulta for r in resultados}) == 4
