# Robô Portal da Transparência — Pessoa Física

Robô em Python + Playwright que consulta uma pessoa física no
[Portal da Transparência](https://portaldatransparencia.gov.br) por **nome, CPF ou NIS**
(com o filtro opcional **"Beneficiário de Programa Social"**), coleta o panorama da
relação da pessoa com o Governo Federal, captura a tela como evidência (PNG em Base64),
entra no detalhe de cada benefício e devolve tudo em **JSON**.

Roda em **modo headless**, aceita **execuções simultâneas** e é exposto como **API HTTP
documentada em Swagger/OpenAPI**.

> ⚠️ **Limitação conhecida:** o portal está atrás do AWS WAF, que às vezes exige
> verificação humana (CAPTCHA) de navegadores headless. Quando isso acontece o robô
> **não** tenta resolver nem contornar a verificação: devolve um JSON de erro
> `bloqueio_anti_bot` em 10–15 s. Detalhes em [docs/RELATORIO.md](docs/RELATORIO.md#o-bloqueio-anti-bot).

## Fluxo

1. Abre **Pessoas Físicas e Jurídicas** → **Busca de Pessoa Física**.
2. Preenche o termo, abre **Refine a busca** e marca o filtro social (se pedido), busca.
3. Abre o **primeiro registro** da lista e lê o panorama: identificação (nome, CPF, localidade)
   e todas as seções/tabelas (ex.: *Recebimentos de recursos*).
4. Expande as seções e captura a **página inteira** em PNG → Base64.
5. Para cada benefício com link **Detalhar** (Auxílio Brasil, Auxílio Emergencial, Bolsa Família e
   quaisquer outros, como Novo Bolsa Família ou Seguro Defeso), abre o detalhe e coleta **todas**
   as parcelas, não só as 10 da primeira página.
6. Fecha o contexto do navegador e devolve o JSON.

## Instalação

Requer Python 3.11+ (testado com 3.14).

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
```

Configuração por variáveis de ambiente (todas opcionais) — veja [.env.example](.env.example).
Copie para `.env` para ajustar tempo limite, paralelismo etc.

## Uso

### Interface web

Com a API no ar (veja abaixo), abra <http://localhost:8000/>. É uma página simples, servida
pela própria API:

- campo para nome, CPF ou NIS e a caixa do filtro **Beneficiário de Programa Social**;
- cada consulta vira um cartão com cronômetro. Dá para disparar várias sem esperar, e elas
  rodam em paralelo;
- no fim, o cartão mostra a pessoa, as tabelas do panorama, as parcelas coletadas de cada
  benefício e a imagem de evidência (clique para ampliar), além dos botões **Ver JSON** e
  **Baixar JSON** (`<id_consulta>_<AAAAMMDD_HHMMSS>.json`).

### Linha de comando

```bash
python -m robo "NOME COMPLETO DA PESSOA"
python -m robo 12345678909          # CPF ou NIS, com ou sem pontuação
python -m robo SOUZA --filtro-social
```

Vários termos no mesmo comando **rodam em paralelo**; cada resultado vira
`saida/<id_consulta>_<AAAAMMDD_HHMMSS>.json`:

```bash
python -m robo 12345678909 "NOME INEXISTENTE XYZ" SOUZA --filtro-social -v
```

### API

```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

- Interface: <http://localhost:8000/> · Swagger: <http://localhost:8000/docs> · ReDoc: <http://localhost:8000/redoc>
- `GET /saude` — verificação de vida
- `POST /consultas`

```bash
curl -X POST http://localhost:8000/consultas \
  -H "Content-Type: application/json" \
  -d '{"termo": "SOUZA", "filtro_beneficiario_programa_social": true}'
```

| HTTP | Quando |
|---|---|
| 200 | Consulta concluída — **inclusive** erros do portal (sem resultados, tempo esgotado, bloqueio anti-bot), com `status: "erro"`. Assim um workflow sempre recebe um JSON para arquivar. |
| 422 | Termo inválido (vazio, CPF/NIS sem 11 dígitos, nome com números). Não ocupa navegador. |

### Docker

```bash
docker build -t robo-transparencia .
docker run -p 8000:8000 robo-transparencia
```

## Saída

Exemplo completo (gerado com dados fictícios): [docs/exemplo-saida.json](docs/exemplo-saida.json).

| Campo | Conteúdo |
|---|---|
| `id_consulta` | Identificador único da consulta |
| `status` | `sucesso` ou `erro` |
| `data_hora_consulta` | ISO 8601, horário de Brasília |
| `parametros` | termo, tipo detectado (`nome` / `cpf_ou_nis`) e filtro |
| `codigo_erro`, `mensagem` | Preenchidos em erro (ver tabela abaixo) |
| `pessoa` | `nome`, `cpf` (mascarado, como o portal exibe), `localidade`, `campos` |
| `panorama` | Seções do panorama com as tabelas lidas célula a célula |
| `beneficios` | Por benefício: identificação e as tabelas de parcelas completas |
| `evidencia` | `{formato: "png", tela, base64}` — também presente em erros, quando possível |

### Cenários de teste do desafio

| Cenário | Entrada | Saída |
|---|---|---|
| Sucesso (CPF/NIS) | CPF ou NIS existente | `status: sucesso`, dados + evidência |
| Erro (CPF/NIS) | CPF/NIS inexistente | `sem_resultados` · "Não foi possível retornar os dados no tempo de resposta solicitado" |
| Sucesso (Nome) | nome completo | dados do primeiro registro + evidência |
| Erro (Nome) | nome inexistente | `sem_resultados` · "Foram encontrados 0 resultados para o termo …" (frase do portal) |
| Filtrado | sobrenome + `filtro_beneficiario_programa_social` | primeiro registro filtrado + evidência |

Outros códigos de erro: `tempo_esgotado` (mesma mensagem de tempo de resposta),
`bloqueio_anti_bot`, `termo_invalido`, `erro_interno`.

## Testes

```bash
pytest
```

40 testes, **sem acesso à internet**. O fluxo completo (cliques, busca por XHR, acordeões,
paginação, evidência) roda contra um **portal falso** servido pelo roteamento do Playwright
([tests/portal_falso.py](tests/portal_falso.py)), que reproduz a estrutura do portal real
com dados fictícios. Cobre os cinco cenários acima, o CAPTCHA, o tempo esgotado e quatro
consultas simultâneas sem mistura de dados.

## Estrutura

```
robo/
  config.py      variáveis de ambiente
  termo.py       classificação do termo e mensagens dos cenários de erro
  navegador.py   um Chromium compartilhado, um contexto isolado por consulta, semáforo
  portal.py      passos no site e JavaScript de extração
  paginacao.py   coleta completa das tabelas paginadas
  consulta.py    orquestração, tempo limite, JSON
  modelos.py     schema de entrada/saída (também o do Swagger)
  __main__.py    CLI
api/main.py      FastAPI
api/interface.html  página web servida em /
tests/           unitários + fluxo completo no portal falso
docs/            relatório técnico e exemplo de saída
```
