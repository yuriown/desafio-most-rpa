"""Gera docs/make-blueprint.json: o cenário da Parte 2 pronto para importar no Make.

O formato de cada módulo segue exemplos oficiais da Make (github.com/integromat/make-skills)
e exportações reais. Chave de API e URL do túnel ficam como marcadores: o repositório é
público, e os dois se preenchem no Make depois de importar.

Uso: ``python scripts/gerar_blueprint_make.py``
"""

import json
from pathlib import Path

LINK_DRIVE = "https://drive.google.com/file/d/{{4.id}}/view"


def modulo(id_, nome_modulo, versao, mapper, parameters=None, conexao=None, x=None, nome=None, notas=None):
    metadata = {"designer": {"x": (id_ - 1) * 300 if x is None else x, "y": 0}}
    if nome:
        metadata["designer"]["name"] = nome
    if conexao:
        metadata["parameters"] = [{"name": "__IMTCONN__", "type": conexao, "label": "Connection", "required": True}]
    if notas:
        metadata["notes"] = notas
    return {"id": id_, "module": nome_modulo, "version": versao, "parameters": parameters or {},
            "mapper": mapper, "metadata": metadata}


fluxo = [
    {
        "id": 1, "module": "gateway:CustomWebHook", "version": 1,
        "parameters": {"maxResults": 1}, "mapper": {},
        "metadata": {
            "designer": {"x": 0, "y": 0, "name": "Recebe a consulta"},
            "restore": {"parameters": {"hook": {"data": {"editable": "true"}, "label": "consulta-robo"}}},
            "parameters": [
                {"name": "hook", "type": "hook:gateway-webhook", "label": "Webhook", "required": True},
                {"name": "maxResults", "type": "number", "label": "Maximum number of results"},
            ],
        },
    },
    modulo(
        2, "http:ActionSendData", 3,
        parameters={"handleErrors": True},  # "Evaluate all states as errors": 401/422 param o cenário
        mapper={
            "url": "<ENDERECO_DO_TUNEL>/consultas",
            "method": "post",
            "headers": [{"name": "X-API-Key", "value": "<ROBO_API_KEY>"}],
            "bodyType": "raw",
            "contentType": "application/json",
            "data": '{"termo": "{{1.termo}}", "filtro_beneficiario_programa_social": {{if(1.filtro; true; false)}}}',
            # Sem parse: {{2.data}} é o texto exato do JSON, que vai inteiro para o Drive.
            "parseResponse": False,
            "timeout": "300",
        },
        nome="Chama o robô",
        notas="Troque <ENDERECO_DO_TUNEL> e <ROBO_API_KEY>.",
    ),
    modulo(3, "json:ParseJSON", 1, mapper={"json": "{{2.data}}"}, nome="Lê o resultado"),
    modulo(
        4, "google-drive:uploadAFile", 4,
        mapper={"select": "value", "filename": "{{3.nome_arquivo}}", "data": "{{2.data}}"},
        conexao="account", nome="Salva o JSON no Drive",
        notas="Conecte o Google e escolha a pasta Consultas Robô.",
    ),
    modulo(
        5, "google-sheets:addRow", 2,
        mapper={
            "mode": "select", "from": "drive", "spreadsheetId": "", "sheetId": "",
            "includesHeaders": True, "insertDataOption": "INSERT_ROWS", "valueInputOption": "USER_ENTERED",
            # Colunas A..H da planilha "Registro de consultas".
            "values": {
                "0": "{{3.id_consulta}}",
                "1": "{{3.data_hora_consulta}}",
                "2": "{{3.pessoa.nome}}",
                "3": "{{3.pessoa.cpf}}",
                "4": "{{3.parametros.termo}}",
                "5": "{{3.status}}",
                "6": "{{3.mensagem}}",
                "7": LINK_DRIVE,
            },
        },
        conexao="account:google", nome="Registra na planilha",
        notas="Escolha a planilha Registro de consultas (cabeçalho na linha 1).",
    ),
    modulo(
        6, "gateway:WebhookRespond", 1,
        mapper={
            "status": "200",
            "body": '{"id_consulta": "{{3.id_consulta}}", "status": "{{3.status}}", '
                    '"codigo_erro": "{{3.codigo_erro}}", "link_json": "' + LINK_DRIVE + '"}',
            # Aqui o campo é "key"; no módulo HTTP é "name". Importar com "name" deixa o Key vazio.
            "headers": [{"key": "Content-Type", "value": "application/json"}],
        },
        nome="Responde a quem chamou",
    ),
]

blueprint = {
    "name": "Robô Transparência: consulta, Drive e Sheets",
    "flow": fluxo,
    "metadata": {
        "instant": True,
        "version": 1,
        "scenario": {
            "roundtrips": 1, "maxErrors": 3, "autoCommit": True, "autoCommitTriggerLast": True,
            "sequential": False,  # chamadas simultâneas rodam em paralelo
            "slots": None, "confidential": False, "dataloss": False, "dlq": False, "freshVariables": False,
        },
        "designer": {"orphans": []},
        "notes": [
            "Importe em: cenário novo > menu ... > Import Blueprint.",
            "Depois: crie o webhook no módulo 1, preencha URL e chave no módulo 2, "
            "conecte o Google nos módulos 4 e 5 e escolha a pasta e a planilha.",
            "Passo a passo completo em docs/PARTE2.md.",
        ],
    },
}

destino = Path(__file__).resolve().parent.parent / "docs" / "make-blueprint.json"
destino.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(destino)
