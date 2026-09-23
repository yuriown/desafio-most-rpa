from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import api.main as modulo_api
from robo.modelos import Parametros, ResultadoConsulta


CHAVE = "chave-de-teste-123"


@pytest.fixture
def chave_definida():
    """Marca o teste para subir a API com ROBO_API_KEY definida."""
    return CHAVE


@pytest.fixture
def cliente(monkeypatch, request):
    # Um .env local com ROBO_API_KEY não pode mudar o resultado dos testes.
    monkeypatch.delenv("ROBO_API_KEY", raising=False)
    if "chave_definida" in request.fixturenames:
        monkeypatch.setenv("ROBO_API_KEY", CHAVE)
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


def test_interface_na_raiz(cliente):
    resposta = cliente.get("/")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("text/html")
    assert 'id="formulario"' in resposta.text and "/consultas" in resposta.text


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


@pytest.mark.parametrize("cabecalhos", [{}, {"X-API-Key": "errada"}, {"X-API-Key": ""}])
def test_com_chave_definida_recusa_sem_chave_certa(chave_definida, cliente, cabecalhos):
    resposta = cliente.post("/consultas", json={"termo": "MARIA"}, headers=cabecalhos)
    assert resposta.status_code == 401
    assert cliente.chamadas == []


def test_com_chave_definida_aceita_chave_certa(chave_definida, cliente):
    resposta = cliente.post("/consultas", json={"termo": "MARIA"}, headers={"X-API-Key": chave_definida})
    assert resposta.status_code == 200


def test_com_chave_definida_saude_e_interface_continuam_abertas(chave_definida, cliente):
    assert cliente.get("/saude").status_code == 200
    assert cliente.get("/").status_code == 200


def test_nome_arquivo_segue_o_padrao_do_desafio():
    r = ResultadoConsulta(
        id_consulta="a1b2", status="erro", data_hora_consulta=datetime(2026, 9, 23, 7, 5, 9),
        duracao_segundos=0, parametros=Parametros(termo="X"),
    )
    assert r.nome_arquivo == "a1b2_20260923_070509.json"
    assert r.model_dump(mode="json")["nome_arquivo"] == "a1b2_20260923_070509.json"


def test_openapi_publicado(cliente):
    esquema = cliente.get("/openapi.json").json()
    assert "/consultas" in esquema["paths"]
    assert "ResultadoConsulta" in esquema["components"]["schemas"]
