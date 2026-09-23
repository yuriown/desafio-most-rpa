# Relatório técnico

A Parte 1 (robô) vem primeiro; a Parte 2 (hiperautomação) está em
[Parte 2: plataforma e decisões](#parte-2-plataforma-e-decisões).

## Parte 1

### Decisões técnicas

#### Playwright (a biblioteca recomendada) — e por que HTTP puro não bastaria
A busca de pessoas não é um formulário simples: a página chama outro host
(`busca.portaldatransparencia.gov.br`) com um **token reCAPTCHA v3** gerado pelo JavaScript
da página a cada busca. Uma solução só com `requests` teria que falsificar esse token.
Com um navegador real, o token é gerado como para qualquer visitante. Usei a API
**assíncrona** do Playwright, porque ela permite várias consultas no mesmo processo.

#### Concorrência: um navegador, um contexto por consulta
Um único processo Chromium é compartilhado. Cada consulta recebe o seu próprio
`BrowserContext`, com cookies, cache e armazenamento isolados, o que é mais leve do que um
navegador por consulta e evita que as consultas se misturem. Um semáforo
(`ROBO_MAX_SIMULTANEAS`) limita o paralelismo, para não sobrecarregar a máquina nem o portal.
A API é assíncrona (FastAPI + uvicorn), então as requisições simultâneas são atendidas em paralelo.

#### Tabelas de parcelas lidas do JSON que alimenta a tela
As tabelas de detalhe mostram 10 linhas por vez. Em vez de clicar página por página, o robô
captura a chamada XHR que alimenta cada tabela (`.../recebido/resultado`,
`.../sacado/resultado`) e a repete de dentro da página, com a mesma sessão e o mesmo token,
pedindo páginas maiores. Assim os dados vêm estruturados e completos.

**A armadilha:** com `paginacaoSimples=true`, o portal devolve `recordsTotal =
9223372036854775807` (o maior valor de um long) sempre que existe uma próxima página. O total
só é real quando a página vem incompleta. Por isso a coleta **ignora `recordsTotal`** e pagina
até receber uma página menor do que a pedida. Conferi no portal real: 81 e 74 parcelas de um
Bolsa Família, tanto com página de 200 (1 chamada) quanto com página de 10 (9 e 8 chamadas),
sem duplicatas.

#### Panorama lido de forma genérica
Em vez de procurar só pelos três benefícios citados no desafio, o robô lê todas as seções
(acordeões) e todas as tabelas do panorama, e segue todo link **Detalhar** que aponte para
`/beneficios/`. Assim ele cobre Auxílio Brasil, Auxílio Emergencial e Bolsa Família, e também
Novo Bolsa Família, Seguro Defeso, Gás do Povo etc., que aparecem em pessoas reais. Se o
detalhe de um benefício falhar, o erro fica registrado naquele benefício e o resto da consulta segue.

#### Mensagens de erro exatamente como nos cenários
- **Nome inexistente:** o robô repassa a frase do próprio portal ("Foram encontrados 0
  resultados para o termo …").
- **CPF/NIS inexistente:** o portal também diz "0 resultados", mas o desafio pede
  "Não foi possível retornar os dados no tempo de resposta solicitado". O robô distingue pelo
  tipo do termo: 11 dígitos é CPF/NIS. Os dois têm 11 dígitos e o portal aceita ambos no mesmo
  campo, então o tipo se chama `cpf_ou_nis`.
- **Tempo esgotado** (limite total por consulta ou de cada ação) usa a mesma mensagem.

#### Todos os erros voltam como JSON
Com a Parte 2 em vista, a API responde **200 com `status: "erro"`** para os erros do portal:
o workflow sempre recebe um JSON para arquivar no Drive, com evidência da tela quando
possível. Só termo inválido volta 422, e sem ocupar um navegador.

#### Interface web servida pela própria API
Além da API com Swagger (o diferencial pedido), a API serve em `/` uma página simples para
usar o robô sem montar requisições. É HTML e JavaScript puros, sem etapa de build: um
formulário com o termo e o filtro, e um cartão por consulta com cronômetro, resultado,
evidência e download do JSON. Como cada envio é uma requisição independente, dá para
disparar várias consultas seguidas, o que serve para demonstrar a execução simultânea.

#### Configuração e segurança
Toda a configuração vem de variáveis de ambiente (`.env.example`), sem nada fixo no código.
O robô não usa credenciais no portal. A API aceita uma chave (`ROBO_API_KEY`, no cabeçalho
`X-API-Key`), obrigatória quando ela é exposta na internet; a comparação usa
`secrets.compare_digest`, que não vaza pelo tempo de resposta. No banner de cookies, o robô
escolhe **rejeitar os opcionais**. Nos logs, CPF/NIS aparece como `***`.

### Desafios enfrentados

#### O bloqueio anti-bot
O portal está atrás do **AWS WAF** (CloudFront). Para o Chromium headless, ele às vezes
responde com status 202, cabeçalho `x-amzn-waf-action` e uma página "Human Verification"
com CAPTCHA. Na primeira execução do robô a página real carregou; nas seguintes, a
verificação apareceu com frequência.

**Decisão: o robô não contorna essa proteção.** Nada de resolver o CAPTCHA, esconder que é
headless (user-agent falso, plugins "stealth") ou tentar em loop até passar. Contornar um
controle anti-bot de um sistema do governo não é uma prática que eu colocaria num produto.

O que o robô faz:
1. Reconhece a verificação (cabeçalho do WAF, título da página, `#captcha-container`).
2. Espera alguns segundos (`ROBO_ESPERA_VERIFICACAO_S`), porque a verificação *silenciosa* é
   resolvida pelo JavaScript da própria página, como em qualquer navegador.
3. Se a página escalar para CAPTCHA, encerra com `bloqueio_anti_bot`, em 10–15 s, com a tela da
   verificação como evidência, em vez de travar até o tempo limite.

Caminhos legítimos para produção: combinar com o órgão uma liberação do IP do robô, ou usar a
[API oficial do Portal](https://api.portaldatransparencia.gov.br) com chave própria. A API
oficial cobre CPF/NIS e benefícios, mas não busca por nome nem gera a evidência de tela.

#### Validar sem depender do site
Como o WAF torna o site imprevisível para headless, a validação foi feita em três camadas:
1. **Reconhecimento no site real, com um navegador comum:** estrutura das páginas, endpoints,
   tokens e o comportamento dos cenários de erro.
2. **Os extratores do robô rodados no site real:** o JavaScript de `portal.py` e a lógica de
   paginação, executados nas páginas reais. Os resultados bateram.
3. **Portal falso** (`tests/portal_falso.py`): reproduz a estrutura do portal com dados
   fictícios e roda o fluxo completo do Playwright sem internet, incluindo os cinco cenários,
   o CAPTCHA, o tempo esgotado e as consultas simultâneas. Para provar que os testes
   detectam defeitos, quebrei de propósito a paginação e o filtro social; os testes certos
   falharam.

#### Outros detalhes do site
- O conteúdo dos acordeões já vem no HTML mesmo com eles fechados. O robô os expande antes da
  captura apenas para que a evidência mostre os dados.
- O botão "Detalhar" repete o mesmo `id` em todas as linhas, então os links são localizados
  pelo `href`.
- Nas páginas de detalhe, o rótulo dos campos é `<b>`; no panorama, é `<strong>`. O
  extrator aceita os dois.

## Parte 2: plataforma e decisões

Guia de montagem e teste: [PARTE2.md](PARTE2.md). Cenário pronto para importar:
[make-blueprint.json](make-blueprint.json).

### Plataforma escolhida: Make.com
- **Cobre o fluxo inteiro no plano gratuito:** webhook, requisição HTTP com tempo limite de
  até 300 s, Google Drive e Google Sheets. No Zapier gratuito, o módulo de webhook é pago.
- **Google por OAuth 2.0:** a conexão é autorizada na tela do Make; nenhuma senha ou chave do
  Google passa pelo robô nem fica no repositório.
- **Cenário versionável:** o blueprint é um JSON no repositório, gerado por script e sem
  segredos (a chave e a URL ficam como marcadores).
- **Execução simultânea nativa:** cenários com webhook processam chamadas em paralelo quando o
  processamento sequencial está desligado, que é como o blueprint vem configurado.

### Como o fluxo funciona
Webhook recebe `{termo, filtro}` › HTTP chama `POST /consultas` com `X-API-Key` › o JSON
devolvido vai **inteiro** para o Drive › uma linha vai para a planilha › o webhook responde
com o identificador, o status e o link.

- **Nome do arquivo:** a API já devolve `nome_arquivo` no padrão
  `[id_consulta]_[AAAAMMDD_HHMMSS].json`. Montar isso com fórmula de data no Make seria frágil
  (fuso e fração de segundo), então a regra fica num lugar só, usado também pela CLI e pela
  interface.
- **Resposta sem parse no HTTP:** o módulo HTTP não interpreta a resposta, para que o arquivo
  no Drive seja byte a byte o JSON do robô. Um módulo *Parse JSON* separado lê os campos da
  planilha.
- **Erros também são arquivados:** como a API responde 200 com `status: "erro"`, uma consulta
  sem resultado ou barrada pelo portal gera arquivo e linha do mesmo jeito, com a evidência.
  Só chave errada (401) e termo inválido (422) interrompem o cenário.
- **Planilha:** identificador, data/hora, nome, CPF, termo, status, mensagem e o link direto
  (`https://drive.google.com/file/d/<id>/view`). As colunas de status e mensagem, a mais do
  que o desafio pede, explicam as linhas de erro.

### API online
O Make roda na nuvem e precisa alcançar o robô. Usei um *quick tunnel* do Cloudflare para a
API rodando localmente (`scripts/demo.ps1` sobe os dois): é gratuito, não pede conta nem
porta aberta no roteador. Um servidor na nuvem sairia de um IP de datacenter, que o WAF do
portal tende a barrar ainda mais, e os planos gratuitos com 512 MB de memória mal aguentam o
Chromium. Para produção, o `Dockerfile` do repositório roda em qualquer serviço de
contêineres.

### Desafios da Parte 2
- **Limite de 100 s do túnel:** a Cloudflare encerra a requisição que passa de 100 s sem
  resposta. O limite de cada consulta foi baixado para 90 s (`ROBO_TIMEOUT_CONSULTA_S`), para o
  robô sempre responder, com erro de tempo se for o caso, antes do corte.
- **Endereço efêmero:** o endereço do túnel muda a cada execução. Por isso ele fica como
  marcador no blueprint e o script mostra o valor a colar no Make.
- **DNS da rede local:** logo depois de criado, o endereço não resolvia pela rede daqui (o DNS
  guardava o "não existe" da primeira consulta). Pelo DNS público resolveu na hora, e o Make
  não é afetado. O teste de ponta a ponta pela internet, com o DNS público, passou: `/saude`
  respondeu, sem chave veio 401 e com chave a consulta voltou 200 em 12,6 s.
- **Segurança da exposição:** com a API na internet, `/consultas` exige a chave, e o túnel só
  fica de pé durante a demonstração.
