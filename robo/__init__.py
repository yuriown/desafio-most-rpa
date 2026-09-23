"""Robô de consulta de Pessoa Física no Portal da Transparência."""

from .config import Config, carregar_config
from .consulta import executar_consulta
from .modelos import ConsultaEntrada, ResultadoConsulta
from .navegador import GerenciadorNavegador

__all__ = [
    "Config",
    "ConsultaEntrada",
    "GerenciadorNavegador",
    "ResultadoConsulta",
    "carregar_config",
    "executar_consulta",
]
