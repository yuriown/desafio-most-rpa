"""Modelos de entrada e saída. São também o schema publicado no Swagger/OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConsultaEntrada(BaseModel):
    termo: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nome, CPF ou NIS (obrigatório).",
        examples=["MARIA DA SILVA", "12345678909"],
    )
    filtro_beneficiario_programa_social: bool = Field(
        False,
        description='Aplica o filtro "Beneficiário de Programa Social" na busca.',
    )


class Parametros(BaseModel):
    termo: str
    tipo_termo: Literal["cpf_ou_nis", "nome"] | None = None
    filtro_beneficiario_programa_social: bool = False


class Tabela(BaseModel):
    """Tabela lida da tela, célula a célula."""

    rotulo: str | None = Field(None, description="Título exibido acima da tabela.")
    colunas: list[str]
    linhas: list[dict[str, Any]]


class SecaoPanorama(BaseModel):
    titulo: str
    tabelas: list[Tabela]


class Pessoa(BaseModel):
    nome: str | None = None
    cpf: str | None = Field(None, description="CPF como o portal exibe (mascarado).")
    localidade: str | None = None
    campos: dict[str, str] = Field(default_factory=dict, description="Todos os campos de identificação exibidos.")


class TabelaDetalhe(BaseModel):
    """Tabela de parcelas de um benefício, lida direto do JSON que alimenta a tela."""

    nome: str = Field(..., description='Nome do conjunto no portal, ex.: "recebido", "sacado", "disponibilizado".')
    endpoint: str
    total_registros: int
    completa: bool = Field(..., description="False se a coleta parou no limite de páginas.")
    registros: list[dict[str, Any]]


class DetalheBeneficio(BaseModel):
    programa: str
    url: str
    identificacao: dict[str, str] = Field(default_factory=dict)
    tabelas: list[TabelaDetalhe] = Field(default_factory=list)
    erro: str | None = Field(None, description="Preenchido se só este detalhe falhou.")


class Evidencia(BaseModel):
    formato: Literal["png"] = "png"
    tela: str = Field(..., description="Qual tela foi capturada.")
    base64: str


class ResultadoConsulta(BaseModel):
    id_consulta: str
    status: Literal["sucesso", "erro"]
    data_hora_consulta: datetime
    duracao_segundos: float
    parametros: Parametros
    codigo_erro: str | None = None
    mensagem: str | None = None
    total_resultados_busca: int | None = None
    url_pessoa: str | None = None
    pessoa: Pessoa | None = None
    panorama: list[SecaoPanorama] = Field(default_factory=list)
    beneficios: list[DetalheBeneficio] = Field(default_factory=list)
    evidencia: Evidencia | None = None
