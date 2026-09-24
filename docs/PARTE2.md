# Parte 2 — Hiperautomação com Make.com

```
curl / formulário ──▶ Make: webhook ──▶ HTTP POST /consultas (robô) ──▶ Parse JSON
                                                                         │
             resposta com o link ◀── Webhook response ◀── Sheets: add row ◀── Drive: upload
```

1. Um **webhook** do Make recebe `{"termo": "...", "filtro": true|false}`.
2. O Make chama o robô (`POST /consultas`) pela internet, com a chave no cabeçalho `X-API-Key`.
3. O JSON devolvido vai para o **Google Drive** com o nome `[id_consulta]_[AAAAMMDD_HHMMSS].json`,
   que a API já entrega pronto no campo `nome_arquivo`.
4. Uma linha é adicionada ao **Google Sheets**: identificador, data/hora, nome, CPF, termo,
   status, mensagem e o link direto do arquivo no Drive.
5. Quem chamou o webhook recebe de volta o identificador, o status e o link.

## Por que o Make

- O plano gratuito tem webhook, requisição HTTP, Google Drive e Google Sheets. No Zapier
  gratuito, o módulo de webhook é pago.
- A conexão com o Google é por **OAuth 2.0**, feita na própria tela do Make: nenhuma senha
  ou chave do Google passa pelo robô.
- O cenário pode ser exportado como JSON (*blueprint*) e versionado no repositório
  ([make-blueprint.json](make-blueprint.json)).

## 1. Subir a API com chave

Gere uma chave aleatória e guarde-a no `.env` (que não vai para o git). Na mesma hora, limite
cada consulta a 90 s, abaixo dos 100 s que o túnel do passo 2 espera por uma resposta:

```bash
python -c "import secrets; print('ROBO_API_KEY=' + secrets.token_urlsafe(32)); print('ROBO_TIMEOUT_CONSULTA_S=90')" >> .env
```

## 2. Expor a API na internet

O Make roda na nuvem e precisa alcançar a API. Um *quick tunnel* do Cloudflare faz isso sem
conta e sem abrir porta no roteador.

**Instalar o `cloudflared`:** `winget install --id Cloudflare.cloudflared` pede permissão de
administrador. Sem ela, baixe o executável avulso do repositório oficial e confira o SHA-256
com o publicado na página da versão:

```bash
gh release download --repo cloudflare/cloudflared --pattern cloudflared-windows-amd64.exe --dir %LOCALAPPDATA%\Programs\cloudflared
```

Renomeie o arquivo para `cloudflared.exe`.

**Subir API e túnel juntos:**

```bash
powershell -ExecutionPolicy Bypass -File scripts\demo.ps1
```

O script confere se a chave está no `.env`, sobe a API e o túnel e mostra o endereço
`https://<nome-aleatório>.trycloudflare.com`. **O endereço muda a cada execução**: atualize a
URL no módulo HTTP do Make sempre que reiniciar. `Ctrl+C` encerra os dois.

Só `/consultas` exige a chave; `/saude`, `/docs` e a interface ficam abertas.

> A rede local pode demorar a resolver o nome novo (o DNS guarda o "não existe" da primeira
> tentativa). O Make, na nuvem, não tem esse problema. Para testar daqui, use o DNS público:
> `curl --doh-url https://1.1.1.1/dns-query https://<endereço>/saude`

## 3. Preparar o Google

- No Google Drive, crie a pasta **Consultas Robô**.
- No Google Sheets, crie a planilha **Registro de consultas** com esta primeira linha
  (cabeçalho), da coluna A à H:

| id_consulta | data_hora_consulta | nome | cpf | termo | status | mensagem | link_json |
|---|---|---|---|---|---|---|---|

## 4. Montar o cenário no Make

### Opção A: importar o blueprint (mais rápido)

1. No Make: **Create a new scenario** › menu **…** › **Import Blueprint** › escolha
   [make-blueprint.json](make-blueprint.json).
2. **Módulo 1:** clique em *Add* para criar o webhook e copie a URL. Depois, *Redetermine data
   structure* e envie o `curl` de exemplo abaixo (1 · Custom webhook).
3. **Módulo 2:** troque `<ENDERECO_DO_TUNEL>` pelo endereço do túnel e `<ROBO_API_KEY>` pela
   chave do `.env`.
4. **Módulos 4 e 5:** conecte a conta Google (OAuth) e escolha a pasta **Consultas Robô** e a
   planilha **Registro de consultas**.
5. **Módulo 3 (opcional):** para ver os campos no painel de mapeamento, gere a *data structure*
   a partir de [exemplo-saida.json](exemplo-saida.json). Sem ela, o cenário funciona igual.

O blueprint é gerado por [scripts/gerar_blueprint_make.py](../scripts/gerar_blueprint_make.py),
com o formato dos módulos tirado dos exemplos oficiais da Make. Foi importado e rodado numa
conta real em 24/09/2026: os seis módulos passaram, e três chamadas simultâneas geraram três
arquivos e três linhas. A primeira importação revelou um defeito (o cabeçalho do módulo 6
usava `name` onde o Make espera `key`, e o campo vinha vazio), já corrigido no gerador. Se a
importação falhar mesmo assim, a opção B monta o mesmo fluxo.

### Opção B: montar à mão

Crie um cenário novo com os módulos abaixo, nesta ordem. Os números entre chaves (`{{2.data}}`)
são as referências do Make: o número é a posição do módulo no cenário.

**1 · Webhooks › Custom webhook**
- Crie o webhook (ex.: `consulta-robo`) e copie a URL.
- Clique em *Redetermine data structure* e envie um exemplo, para o Make aprender os campos:
  ```bash
  curl -X POST <url-do-webhook> -H "Content-Type: application/json" -d "{\"termo\": \"MARIA DA SILVA\", \"filtro\": false}"
  ```

**2 · HTTP › Make a request**
- URL: `https://<endereço-do-túnel>/consultas` · Method: `POST`
- Headers: `X-API-Key` = a chave do `.env`
- Body type: `Raw` · Content type: `JSON (application/json)`
- Request content:
  ```
  {"termo": "{{1.termo}}", "filtro_beneficiario_programa_social": {{if(1.filtro; true; false)}}}
  ```
- **Parse response: Não.** Assim `{{2.data}}` é o texto exato do JSON, que vai inteiro para o Drive.
- Timeout: `300`.
- *Evaluate all states as errors*: Sim. Chave errada (401) ou termo inválido (422) param o cenário.

**3 · JSON › Parse JSON**
- JSON string: `{{2.data}}`
- Data structure: *Add* › *Generator* › cole o conteúdo de [exemplo-saida.json](exemplo-saida.json).

**4 · Google Drive › Upload a File**
- Conecte a conta Google (OAuth, na tela do Make).
- Folder: **Consultas Robô**
- File name: `{{3.nome_arquivo}}` · Data: `{{2.data}}` · Convert: Não

**5 · Google Sheets › Add a Row**
- Spreadsheet: **Registro de consultas** · Sheet: a primeira · Table contains headers: Sim
- Colunas:
  | Coluna | Valor |
  |---|---|
  | id_consulta | `{{3.id_consulta}}` |
  | data_hora_consulta | `{{3.data_hora_consulta}}` |
  | nome | `{{3.pessoa.nome}}` |
  | cpf | `{{3.pessoa.cpf}}` |
  | termo | `{{3.parametros.termo}}` |
  | status | `{{3.status}}` |
  | mensagem | `{{3.mensagem}}` |
  | link_json | `https://drive.google.com/file/d/{{4.id}}/view` |

**6 · Webhooks › Webhook response**
- Status: `200` · Header: `Content-Type` = `application/json`
- Body:
  ```
  {"id_consulta": "{{3.id_consulta}}", "status": "{{3.status}}", "codigo_erro": "{{3.codigo_erro}}", "link_json": "https://drive.google.com/file/d/{{4.id}}/view"}
  ```

> O termo vai para o corpo do módulo 2 como texto, sem escape: um termo com aspas duplas
> quebraria o JSON e a API responderia 422. Nomes, CPFs e NIS não têm aspas.

Nas configurações do cenário, deixe **Sequential processing desligado**, para que chamadas
simultâneas rodem em paralelo, e ative o cenário (*Scheduling: Immediately*).

## 5. Testar

Uma consulta:

```bash
curl -X POST <url-do-webhook> -H "Content-Type: application/json" -d "{\"termo\": \"SOUZA\", \"filtro\": true}"
```

Várias ao mesmo tempo, para demonstrar a execução simultânea:

```bash
for t in "SOUZA" "NOME INEXISTENTE XYZ" "12345678909"; do curl -s -X POST <url-do-webhook> -H "Content-Type: application/json" -d "{\"termo\": \"$t\", \"filtro\": false}" & done; wait
```

Cada chamada deve gerar um arquivo na pasta **Consultas Robô** e uma linha na planilha,
inclusive as que terminarem em erro (`sem_resultados`, `bloqueio_anti_bot`): o robô sempre
devolve um JSON, e ele sempre é arquivado.

## 6. Atualizar o blueprint depois de ajustar o cenário

Se mudar o cenário no Make, exporte de novo (menu do cenário › *Export Blueprint*) e salve por
cima de `docs/make-blueprint.json`. Antes do commit, **troque a chave do cabeçalho `X-API-Key`
por `<ROBO_API_KEY>` e a URL do túnel por `<ENDERECO_DO_TUNEL>`**: o blueprint guarda os valores
digitados nos módulos, e a chave não pode ir para um repositório público.
