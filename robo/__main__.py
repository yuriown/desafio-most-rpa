"""Linha de comando: ``python -m robo TERMO [TERMO ...] [--filtro-social] [--saida DIR]``.

Vários termos rodam ao mesmo tempo (limitados por ROBO_MAX_SIMULTANEAS), e cada
resultado vira um arquivo ``<id_consulta>_<AAAAMMDD_HHMMSS>.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from .config import carregar_config
from .consulta import executar_consulta
from .modelos import ConsultaEntrada
from .navegador import GerenciadorNavegador


async def _rodar(termos: list[str], filtro: bool, saida: Path) -> int:
    config = carregar_config()
    gerenciador = GerenciadorNavegador(config)
    try:
        resultados = await asyncio.gather(*(
            executar_consulta(gerenciador, config, ConsultaEntrada(termo=t, filtro_beneficiario_programa_social=filtro))
            for t in termos
        ))
    finally:
        await gerenciador.encerrar()

    saida.mkdir(parents=True, exist_ok=True)
    for r in resultados:
        arquivo = saida / r.nome_arquivo
        arquivo.write_text(r.model_dump_json(indent=2), encoding="utf-8")
        resumo = r.pessoa.nome if r.pessoa else r.mensagem
        print(f"{r.status:8} {r.duracao_segundos:6.1f}s  {r.parametros.termo!r} -> {resumo}  [{arquivo}]")
    return 0 if all(r.status == "sucesso" for r in resultados) else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m robo", description=__doc__.splitlines()[0])
    parser.add_argument("termos", nargs="+", help="Nome, CPF ou NIS (um ou mais; rodam em paralelo)")
    parser.add_argument("--filtro-social", action="store_true", help='Filtro "Beneficiário de Programa Social"')
    parser.add_argument("--saida", type=Path, default=Path("saida"), help="Pasta dos JSONs (padrão: ./saida)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(_rodar(args.termos, args.filtro_social, args.saida)))


if __name__ == "__main__":
    main()
