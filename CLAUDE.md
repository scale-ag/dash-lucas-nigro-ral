# CLAUDE.md — Contexto do projeto (Dashboard Lucas Nigro · RAL)

> Este arquivo é lido automaticamente pelo Claude Code ao abrir o repositório.
> Ele carrega TODO o contexto necessário para continuar o trabalho sem depender
> de mensagens anteriores. Mantenha-o atualizado.
>
> Este repositório já está **configurado para o cliente Lucas Nigro** (Funil de
> Sessão Estratégica, Método RaL). Não é mais o template genérico — os valores
> abaixo são reais. Para replicar este modelo para outro cliente, veja
> `GUIA-REPLICACAO.md`.

---

## Status da configuração

- **Repositório:** `scale-ag/dash-lucas-nigro-ral`.
- **URL pública:** `https://scale-ag.github.io/dash-lucas-nigro-ral/`.
- **`build/build.py`:** `SPREADSHEET_ID_FUNIL` (Leads + Vendas), `SPREADSHEET_ID_META`
  (Página 1), `CLIENT_NAME`, `MAIN_PRODUCT`, `MAIN_PRODUCT_PREFIX`, `TAX_FACTOR`
  preenchidos (ver "Fontes de dados" abaixo).
- **Critério de MQL:** `is_qualificado()` em `build.py` — coluna `classificacao`
  (aba Leads) == `"QUALIFICADO"`.
- **`build/app.js` / `build/template.html`:** rótulos de UI e logo já ajustados
  para este cliente (sem referência a "médico"/especialidade médica).
- **`build/identidade-visual.css`:** cores default do template (cliente não pediu
  identidade visual própria).
- **`build/GUIA-RELATORIOS.md`:** contexto do funil preenchido.
- **Insights de Tráfego (opcional, não configurado ainda):** `build/relatorios.json`
  e `build/relatorios_dados.json` começam vazios (`{}`). Para ativar: deixar a
  Routine do Actions `briefing.yml` rodar (gera `relatorios_dados.json`) e criar
  a **Routine do Claude** (`create_trigger` apontando para este repo) que lê os
  números + os 2 guias e escreve `relatorios.json` na `main` (ver "Briefing
  automático" abaixo).

> **Fora do escopo deste projeto:** não há Cloudflare Worker nem chamada paga à
> API da Anthropic no pipeline. A automação de Insights é feita por Routine
> agendada do Claude Code (opcional, acima).

---

## O que é

Dashboard de **Captura de Leads** — um app de BI estático (HTML/CSS/JS
puro + Chart.js via CDN) publicado no **GitHub Pages**, que cruza a lista de
**Leads** com o gerenciador de mídia paga e se atualiza sozinho a cada ~30 min
(build 100% na nuvem via GitHub Actions, disparado externamente pelo cron-job.org).

- **URL pública:** `https://scale-ag.github.io/dash-lucas-nigro-ral/`
- **Somente leitura** das planilhas. Nunca escrever de volta.
- **Análise principal (macro), em todos os gráficos/tabelas/KPIs:** quantidade
  de Leads → Leads Qualificados (MQLs) → Vendas, e o **custo de cada etapa**
  (CPL, CPMQL, CAC) — é a lente central do dashboard, não um detalhe secundário.

## Fontes de dados (Google Sheets)

Duas planilhas — **sem gid fixo**: o build busca cada aba **por nome**
(`gviz/tq?tqx=out:csv&sheet=<nome>`), mais robusto a reordenação de abas que
export por gid.

**Planilha do Funil** — `SPREADSHEET_ID_FUNIL = "1j3EQE4zbRlUVAKyDPTmlnTDP0Jlvw-enQyMPR2LXjfk"`:

| Aba | Colunas |
|-----|---------|
| **Leads** (`SHEET_LEADS`, fonte **única** de leads — não há aba Conversas neste cliente) | `id` · `criado_em` · `nome` · `whatsapp` · `email` · `utm_source` · `utm_medium` · `utm_content` · `utm_term` · `atende_empresas` · `clientes_empresariais` · `objetivo_formacao` · `lead_score` · `classificacao` (**coluna O**, MQL) · `status` · `cidade` · `uf` |
| **Vendas** (`SHEET_VENDAS`) | `transaction_id` · `pago_em` · `status` · `pago` · `comprador` · `email` · `whatsapp` · `valor` · `moeda` · `produto` · `utm_source` · `utm_campaign` · `lead_id` · `casado_por` |

**Planilha Meta Ads** — `SPREADSHEET_ID_META = "1xb5itNu9_No6keCKHyzG7qIPobT46BqfmJ_rP0v4h8c"`, aba **"Página 1"** (`SHEET_META`):
`Day` · `Campaign Name` · `Ad Set Name` · `Ad Name` · `Impressions` · `Link Clicks` · `Landing Page Views` · `Amount Spent`.
Não tem Ad ID, Content Views, Adds to Cart, Subscriptions, nem link de criativo
— essas métricas aparecem "-"/"—" na dash. **Tem** Landing Page Views (ConvLP/CPV
calculáveis, diferente do gap padrão do template genérico).

URL de export CSV (por nome de aba): `https://docs.google.com/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv&sheet=<nome>`

### Regra de Lead Qualificado (MQL)
Coluna `classificacao` da aba Leads (**coluna O**) == `"QUALIFICADO"` (valor
oposto: `"DESQUALIFICADO"`). Lógica em `build.py` → `is_qualificado`. O gráfico
"Leads por perfil profissional" (`app.js`, `renderGeralCore`) colore verde/cinza
pelo mesmo critério, usando a coluna `atende_empresas` como dimensão (não há
"especialidade médica" nesse cliente).

### Cruzamento por UTMs (Leads × Meta Ads)
Cada linha da aba **Leads** já vem com a atribuição de campanha pronta:
`utm_campaign` = `Campaign Name`, `utm_medium` = `Ad Set Name`, `utm_content` =
`Ad Name` (valores idênticos aos do Meta Ads, linha a linha) — `build.py` só
copia esses valores, sem precisar de nenhuma aba intermediária tipo "Conversas".

### Vendas & Faturamento (cruzamento com Vendas)
`build.py` → `build_purchases()` lê a aba **Vendas**, filtra só compras
confirmadas (`pago == "sim"`) e devolve uma lista **não agregada**, uma entrada
por linha: `[{lead_id, phone, d, fat, receita, nm}, ...]` (`d` = `pago_em`, a
data real daquela compra). Em `process()`, as linhas da **Leads** são ordenadas
pela **data já parseada** (`parse_date`, não a string bruta) e indexadas de duas
formas: por `id` (→ `id_attrib`) e pelo **1º lead** (mais antigo) de cada
telefone canônico (→ `phone_attrib`).

Cruzamento de cada venda, nessa ordem: **1) `lead_id`** (FK direta
`Vendas.lead_id` → `Leads.id`, cruzamento exato) · **2) fallback por telefone**
canônico (`canon_phone()` — DDD + últimos 8 dígitos, robusto a DDI "55" e ao 9º
dígito do celular) quando `lead_id` vem vazio. Cada compra vira um registro
próprio em `DATA.sales[]` (`{d, camp, adset, ad, vendas:1, fat, receita}`) com a
**data real da compra** (nunca a data do lead). No navegador, `salesActive()`
(`app.js`) filtra `sales[]` pela mesma data ativa que `leadsActive()`/
`metaActive()`, e os três arrays (`fL`/`fM`/`fS`) se propagam juntos em
`buildAgg`/`daily`/`totals`.

**TODA venda confirmada entra na dash** (regra geral: "todas as vendas entram
na Visão Geral; só as atribuídas ao Meta entram na aba de mídia paga"). Quando
nem `lead_id` nem telefone batem, a venda **ainda conta nos totais/Visão
Geral**, porém como `(sem campanha)` / `src="org"` — some apenas da quebra por
campanha do Meta. `log_unmatched_sales()` loga no build quantas vendas ficaram
sem anúncio de origem.

### Imposto da mídia paga
`TAX_FACTOR = 1.0` em `build.py` — cliente sem imposto/taxa adicional sobre a
conta de mídia. O toggle "Imposto Meta" fica **ativo por padrão**
(`STATE.tax=true` em `app.js`), mas com fator 1.0 não altera nenhum valor.

### Convenções de campanha (do cliente)
Todas as campanhas usam o prefixo `MAIN_PRODUCT_PREFIX = "RAL"`, sem filtrar por
sub-funil — mantém TODAS as campanhas no dashboard. Sigla de etapa observada na
única campanha ativa até agora: `E2-CAP` (Etapa 2 – Captura), dentro do nome
completo `RAL | E2-CAP | P2-FRIO | LEAD | CBO | <data> | LAL`. A aba Leads já
traz `utm_campaign`/`utm_medium`/`utm_content` prontos (ver "Cruzamento por
UTMs" acima) — não precisa de aba intermediária.

## Arquitetura / arquivos

```
build/build.py            # lê os CSVs (read-only), emite REGISTROS BRUTOS (leads[]/meta[]/sales[]/ad_links); render() COSTURA os 4 arquivos abaixo
build/template.html       # esqueleto HTML. Placeholders __STYLES__, __APP_JS__, __DATA_JSON__, __BUILD_ID__, __GENERATED_BRT__
build/identidade-visual.css  # TODAS as cores (tema claro=padrão / escuro). Mexa AQUI p/ trocar só cor
build/estilos.css         # layout/componentes (sidebar, topbar, period-picker, funil, tabelas, gráficos, aba Relatório)
build/app.js              # lógica + renderização (KPIs, funil, tabelas, filtro cruzado, period-picker, heatmap, Relatório)
build/relatorios.json     # Insights de Tráfego por período (aba Relatório) — VERSIONADO; lido no build, sem API. Vazio no template ({}).
build/relatorios_dados.json      # números brutos por período (insumo p/ a Routine escrever relatorios.json) — não lido pelo site. Vazio no template ({}).
build/relatorio_lib.py           # datas/agregação compartilhadas (gerar_relatorios.py + coletar_dados_relatorio.py)
build/coletar_dados_relatorio.py # gera relatorios_dados.json (só números, sem texto) — roda no briefing.yml, 1x/dia
build/gerar_relatorios.py        # gera relatorios.json determinístico (sem IA) — fallback MANUAL, não roda mais sozinho
build/GUIA-RELATORIOS.md            # formato/estrutura dos Insights da aba Relatório (os 7 blocos) — preencher o contexto do funil
build/GUIA-INTERPRETACAO-METRICAS.md # regras de diagnóstico por métrica (High Ticket) — leitura obrigatória p/ redigir
.github/workflows/deploy.yml    # roda build.py e publica no Pages (workflow_dispatch + schedule + push)
.github/workflows/briefing.yml  # roda coletar_dados_relatorio.py e commita relatorios_dados.json na main (cron 1x/dia)
dist/index.html           # saída gerada (gitignored; o Actions reconstrói)
GUIA-REPLICACAO.md        # como replicar este modelo para outros relatórios/clientes
SETUP-CRON.md             # valores exatos do cron-job.org (com marcadores a preencher)
```

### Aba Relatório
Terceira página (sidebar, entre a de mídia paga e o rodapé). **Espelha a Visão
Geral** (mesmo funil/KPIs/gráficos/tabela diária, via `renderGeralCore(REL_IDS)`)
e, abaixo, acrescenta 3 blocos novos + um painel de metas editável:
- **Metas & parâmetros (painel editável)** — no topo da aba: Meta CPMQL, Meta CAC, Volume
  mínimo amostral (MQLs), N dias p/ corte. Persiste em `localStorage['dm_metas']`, default de
  `build.py` (`META_CPMQL`/`META_CAC`=None → "não definida"; `VOLUME_MIN_AMOSTRAL`/`N_DIAS_CORTE`).
  Editar recolore **CPMQL/CAC** nas tabelas de anúncio (verde ≤ meta · amarelo até +30% ·
  vermelho acima) e ajusta o badge Em observação/Avaliável, **tudo ao vivo**
  (`METAS` + `renderRelAds()` em `app.js`).
- **Top Anúncios** e **Piores Anúncios** — 17 colunas + coluna **Status** (Anúncio · Status ·
  Campanha · Conjunto · Gasto · Impr · CPM · CTR · Leads · CPL · MQLs · Tx‑MQL · CPMQL · ConvMQL ·
  Vendas · CAC · Faturamento · ROAS · **Link**). Anúncio, Status e Link ficam **sticky**.
  Ranking pelo **resultado mais profundo disponível** (Venda→MQL), amostra relevante primeiro;
  sem amostra → badge **"Em observação"**. Limiares em `build.py`: `SAMPLE_MIN_SPEND`,
  `SAMPLE_MIN_MQLS`, `TOP_ADS_N`.
- **Insights de Tráfego** — texto por período redigido pelo **Claude** (linguagem de
  gestor de tráfego), lido de `build/relatorios.json` (sem API no build/navegador —
  o site só exibe o texto já pronto). Formato em **4 quadrantes** por período. Cada
  período compara com o período anterior **correto para aquela janela** (regra em
  `relatorio_lib.previous_period`). Chaves de período fixas
  (`hoje/ontem/3d/7d/14d/30d/mes/mespass/todo`), tags `Escalar/Otimizar/Cortar/Observar`.
  Toda a aritmética é pré-calculada em `build/relatorios_dados.json` — a Routine só
  interpreta, nunca recalcula. Regras completas em `build/GUIA-RELATORIOS.md` +
  `build/GUIA-INTERPRETACAO-METRICAS.md`. `app.js` ainda reconhece o formato antigo
  (`{"html": "…"}`) como fallback.

### Briefing automático do gestor (Routine do Claude, sem chamada à API Anthropic)
`build/relatorios.json` pode ser escrito 1×/dia por uma **Routine do Claude**
(Claude Code Remote — mesma infraestrutura de sessão/agente deste repo, agendada;
não é chamada paga à API). Fluxo em 2 etapas, porque o ambiente da Routine não
alcança `docs.google.com` (só o runner do GitHub Actions alcança):
1. `build/coletar_dados_relatorio.py` (GitHub Actions, `.github/workflows/briefing.yml`,
   1×/dia) agrega **só números** em `build/relatorios_dados.json` e commita na `main`.
2. A Routine do Claude lê esse JSON + `build/GUIA-RELATORIOS.md` +
   `build/GUIA-INTERPRETACAO-METRICAS.md`, redige `build/relatorios.json` e faz
   commit/push direto na `main`, disparando o `deploy.yml`. **Precisa ser criada
   por cliente** (`create_trigger` apontando para o repo novo) — não vem pronta.

`build/gerar_relatorios.py` (gerador determinístico, sem IA) continua no repo só
como **fallback manual**. Limitação conhecida: usa os defaults de `build.py`
(`META_CPMQL`/`META_CAC`/`VOLUME_MIN_AMOSTRAL`/`N_DIAS_CORTE`), não o que o gestor
editou no painel (fica em `localStorage`).

Funil completo: `Impressões → Cliques → Leads → MQLs → Agendamentos → Reuniões
Realizadas → Vendas → Faturamento`. Enquanto só houver mídia paga × Leads, o funil
vai até MQL; Agendamentos/Reuniões/Vendas/Fat aparecem "-" até chegar a lista do
comercial.

### Link do criativo (aba de mídia paga)
`build.py` lê uma coluna opcional de permalink do criativo na aba de mídia →
mapa `ad_links` (anúncio → 1 permalink). Usado no "Link" das tabelas Top/Piores.
Sem a coluna, o link vira "—".

> **Layout modular:** o front-end é separado em `identidade-visual.css` + `estilos.css`
> + `app.js`, costurados por `render()` nos placeholders `__STYLES__`/`__APP_JS__`.
> Página 1 usa **funil vertical de leads** + KPIs secundários. Topbar tem
> **seletor de período em calendário** (default "Este mês"). **Heatmap** = cor FIXA
> por métrica (só opacidade varia): **Gasto=vermelho · Leads=azul · MQLs=ciano ·
> Vendas=verde · ROAS=amarelo** (`--heat-gasto/leads/mqls/vendas/roas`).

O `build.py` **não agrega**: exporta as linhas cruas e TODA a lógica (filtros de
data, filtro cruzado, KPIs, tabelas, gráficos, heatmap, imposto) roda no navegador.

## Rodar/testar local

```bash
python build/build.py --leads-file leads.csv --meta-file meta.csv --out dist/index.html
# (o sandbox do agente NÃO alcança docs.google.com; use CSVs locais para testar.
#  O runner do GitHub Actions tem internet e busca os CSVs ao vivo.)
```

## Especificação funcional (resumo)

Três **páginas separadas** (sidebar):
1. **Visão Geral de Leads** — funil vertical (Gasto → Impressões → Cliques → Leads →
   MQLs → Vendas/Faturamento) + KPIs secundários; gráfico combinado diário +
   tabela diária com heatmap (todos os leads); barras por origem/faixa/plataforma/profissão.
2. **Captura mídia paga** — funil em etapas; combinado diário; barras por utm_content;
   tabela diária com heatmap (só mídia paga); 3 tabelas hierárquicas Campanha →
   Conjunto → Anúncio, cada uma com gráfico de linha embaixo.
3. **Relatório** — espelha a Visão Geral + painel de Metas editável + Top/Piores
   Anúncios (17 colunas + Status) + Insights de Tráfego. Ver `build/GUIA-RELATORIOS.md`.

**Ordem das colunas nas tabelas:** `Data · Dia · Gasto · CPM · CTR · ConvForm · Leads ·
CPL · Tx‑MQL · MQLs · CPMQL · ConvMQL · Vendas · CAC · Fat. · Receita · ROAS`. Nas
tabelas diárias entram também **Checkouts** e **VisCHK** (da coluna "Adds to Cart"
do Meta Ads, proxy de Checkout). Sem essas colunas, ficam "-".

**Regras obrigatórias das tabelas** (ver `GUIA-REPLICACAO.md`): cabeçalho sticky;
ordenação tri‑state; colunas redimensionáveis (persist localStorage); linha
"Total Geral" fixa; dimensão nunca truncada; seleção com toggle + Ctrl multi;
filtro cruzado bidirecional; tabela diária com último dia no topo; heatmap de cor
fixa por métrica.

## Lacunas de dados (comuns até o cliente enviar mais fontes)
- **Agendamentos / Reuniões Realizadas** → precisam da lista do comercial; aparecem "-".
- **Page Views, CR, CPV, ConvLP** → precisam de uma fonte de page views.
- Enquanto não vierem, essas métricas aparecem como "-".

## Publicação — problemas conhecidos
1. **Push:** se a integração GitHub da sessão for somente‑leitura (403), o caminho
   é `git push` direto para `github.com` com o **PAT do usuário**. Nunca gravar o
   token no `.git/config` (usar URL efêmera `https://x-access-token:<TOKEN>@github.com/...`).
2. **cron-job.org só funciona na `main`:** `workflow_dispatch` só existe na branch
   padrão. Levar `build/` + `.github/workflows/deploy.yml` para a `main`.
3. **Pages liga sozinho:** `actions/configure-pages@v5` com `enablement: true`
   (precisa `permissions: pages: write, id-token: write`).
4. **Proxy do sandbox:** o ambiente do agente costuma NÃO alcançar `docs.google.com`,
   `*.github.io` nem a API REST de Actions/Pages — mas o runner do Actions alcança tudo.
5. **Token exposto:** se um token foi colado no chat, **revogar e gerar um novo**.

## Branch / git
- Desenvolvimento na branch designada da sessão; manter sincronizada com `main`.
