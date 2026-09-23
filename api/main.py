"""API HTTP do robô. Documentação interativa em /docs (Swagger) e /redoc.

Rodar: ``uvicorn api.main:app --host 0.0.0.0 --port 8000``
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from robo import ConsultaEntrada, GerenciadorNavegador, ResultadoConsulta, carregar_config, executar_consulta
from robo.erros import TermoInvalido
from robo.termo import classificar_termo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI) -> AsyncIterator[None]:
    config = carregar_config()
    app.state.config = config
    # O navegador só abre na primeira consulta; aqui só se garante o fechamento.
    app.state.navegador = GerenciadorNavegador(config)
    try:
        yield
    finally:
        await app.state.navegador.encerrar()


app = FastAPI(
    title="Robô Portal da Transparência",
    version="1.0.0",
    description=(
        "Consulta uma pessoa física no Portal da Transparência (por nome, CPF ou NIS), "
        "coleta o panorama da relação com o Governo Federal e o detalhe de cada benefício, "
        "e devolve tudo em JSON com a evidência da tela em Base64.\n\n"
        "Consultas simultâneas são aceitas; o limite de navegadores em paralelo é "
        "`ROBO_MAX_SIMULTANEAS` e as demais aguardam na fila."
    ),
    lifespan=ciclo_de_vida,
)


@app.get("/saude", summary="Verificação de vida da API")
async def saude() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/consultas",
    response_model=ResultadoConsulta,
    summary="Executa uma consulta de pessoa física",
    responses={
        200: {"description": 'Consulta concluída. Erros do portal (sem resultados, tempo esgotado, '
                             'bloqueio anti-bot) também voltam 200, com `status: "erro"` e `mensagem`.'},
        422: {"description": "Termo inválido (vazio, CPF/NIS sem 11 dígitos, nome com números)."},
    },
)
async def consultar(entrada: ConsultaEntrada, request: Request) -> ResultadoConsulta:
    # Valida antes de ocupar um navegador.
    try:
        classificar_termo(entrada.termo)
    except TermoInvalido as erro:
        raise HTTPException(status_code=422, detail=erro.mensagem) from erro
    return await executar_consulta(request.app.state.navegador, request.app.state.config, entrada)
