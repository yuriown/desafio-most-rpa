import pytest

from robo.erros import MSG_TEMPO_ESGOTADO, TermoInvalido
from robo.termo import TipoTermo, classificar_termo, mensagem_sem_resultados


@pytest.mark.parametrize("entrada, esperado", [
    ("123.456.789-09", "12345678909"),
    ("12345678909", "12345678909"),
    ("1.234.567.890-1", "12345678901"),  # NIS formatado
    (" 123 456 789 09 ", "12345678909"),
])
def test_cpf_ou_nis_normalizado(entrada, esperado):
    assert classificar_termo(entrada) == (esperado, TipoTermo.CPF_OU_NIS)


@pytest.mark.parametrize("entrada, esperado", [
    ("maria  da   silva", "maria da silva"),
    ("JOSÉ D'ÁVILA", "JOSÉ D'ÁVILA"),
    ("SOUZA", "SOUZA"),
])
def test_nome_normalizado(entrada, esperado):
    assert classificar_termo(entrada) == (esperado, TipoTermo.NOME)


@pytest.mark.parametrize("entrada", ["", "   ", "123", "1234567890123", "---", "MARIA 123"])
def test_termo_invalido(entrada):
    with pytest.raises(TermoInvalido):
        classificar_termo(entrada)


def test_cpf_inexistente_usa_mensagem_de_tempo():
    texto = "Foram encontrados 0 resultados para o termo 12345678909"
    assert mensagem_sem_resultados(TipoTermo.CPF_OU_NIS, "12345678909", texto) == MSG_TEMPO_ESGOTADO


def test_nome_inexistente_repassa_frase_do_portal():
    texto = "Foram encontrados  0 resultados\n para o termo NOME QUALQUER"
    assert mensagem_sem_resultados(TipoTermo.NOME, "NOME QUALQUER", texto) == (
        "Foram encontrados 0 resultados para o termo NOME QUALQUER"
    )


def test_nome_inexistente_sem_frase_na_tela():
    assert mensagem_sem_resultados(TipoTermo.NOME, "FULANO", None) == (
        "Foram encontrados 0 resultados para o termo FULANO"
    )
