from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import api.main as modulo_api
from robo.modelos import Parametros, ResultadoConsulta


@pytest.fixture
def cliente(monkeypatch):
    chamadas = []

    async def consulta_falsa(gerenciador, config, entrada):
        chamadas.append(entrada)
        return ResultadoConsulta(
            id_consulta="abc", status="sucesso", data_hora_consulta=datetime(2026, 1, 1),
            duracao_segundos=1.0, parametros=Parametros(termo=entrada.termo),
        )

    monkeypatch.setattr(modulo_api, "executar_consulta", consulta_falsa)
    with TestClient(modulo_api.app) as c:
        c.chamadas = chamadas
        yield c


def test_saude(cliente):
    assert cliente.get("/saude").json() == {"status": "ok"}


def test_consulta_valida(cliente):
    resposta = cliente.post("/consultas", json={"termo": "MARIA", "filtro_beneficiario_programa_social": True})
    assert resposta.status_code == 200
    assert resposta.json()["id_consulta"] == "abc"
    assert cliente.chamadas[0].filtro_beneficiario_programa_social is True


@pytest.mark.parametrize("corpo", [{"termo": "123"}, {"termo": ""}, {}])
def test_termo_invalido_e_422(cliente, corpo):
    assert cliente.post("/consultas", json=corpo).status_code == 422
    assert cliente.chamadas == []


def test_openapi_publicado(cliente):
    esquema = cliente.get("/openapi.json").json()
    assert "/consultas" in esquema["paths"]
    assert "ResultadoConsulta" in esquema["components"]["schemas"]
