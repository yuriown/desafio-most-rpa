"""Gera docs/exemplo-saida.json a partir do portal falso (dados fictícios).

Uso: ``python -m tests.gerar_exemplo``
"""

import asyncio
import json
from pathlib import Path

from robo import ConsultaEntrada, GerenciadorNavegador, executar_consulta

from . import portal_falso
from .test_fluxo import CONFIG


async def main() -> None:
    gerenciador = GerenciadorNavegador(CONFIG, portal_falso.instalar)
    try:
        r = await executar_consulta(gerenciador, CONFIG, ConsultaEntrada(termo="FULANO DE TAL"))
    finally:
        await gerenciador.encerrar()
    dados = json.loads(r.model_dump_json())
    dados["evidencia"]["base64"] = dados["evidencia"]["base64"][:60] + "...(truncado no exemplo)"
    for beneficio in dados["beneficios"]:
        for tabela in beneficio["tabelas"]:
            tabela["registros"] = tabela["registros"][:2] + (["...(truncado no exemplo)"] if len(tabela["registros"]) > 2 else [])
    destino = Path("docs/exemplo-saida.json")
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    print(destino)


asyncio.run(main())
