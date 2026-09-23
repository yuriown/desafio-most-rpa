"""Ciclo de vida do navegador compartilhado.

Um único processo Chromium atende todas as consultas; cada consulta ganha o seu
próprio ``BrowserContext`` (cookies, cache e armazenamento isolados). Um semáforo
limita quantas rodam ao mesmo tempo, para não sobrecarregar a máquina nem o portal.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

from .config import Config


PrepararContexto = Callable[[BrowserContext], Awaitable[None]]


class GerenciadorNavegador:
    def __init__(self, config: Config, preparar_contexto: PrepararContexto | None = None):
        self._config = config
        # Gancho chamado em cada contexto novo (os testes o usam para servir um portal falso).
        self._preparar_contexto = preparar_contexto
        self._playwright: Playwright | None = None
        self._navegador: Browser | None = None
        self._trava = asyncio.Lock()
        self._semaforo = asyncio.Semaphore(config.max_simultaneas)

    async def _garantir_navegador(self) -> Browser:
        # Abre o navegador na primeira consulta (e reabre se tiver caído).
        async with self._trava:
            if self._navegador is None or not self._navegador.is_connected():
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._navegador = await self._playwright.chromium.launch(headless=self._config.headless)
            return self._navegador

    @asynccontextmanager
    async def contexto(self) -> AsyncIterator[BrowserContext]:
        async with self._semaforo:
            navegador = await self._garantir_navegador()
            ctx = await navegador.new_context(
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                viewport={"width": 1366, "height": 900},
            )
            ctx.set_default_timeout(self._config.timeout_acao_ms)
            try:
                if self._preparar_contexto is not None:
                    await self._preparar_contexto(ctx)
                yield ctx
            finally:
                await ctx.close()

    async def encerrar(self) -> None:
        async with self._trava:
            if self._navegador is not None:
                await self._navegador.close()
                self._navegador = None
            if self._playwright is not None:
                await self._playwright.stop()
                self._playwright = None
