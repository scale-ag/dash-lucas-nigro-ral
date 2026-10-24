#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera a dashboard estatica (index.html) a partir de 3 abas em 2 planilhas do
cliente Lucas Nigro (Funil "RAL" / Metodo RaL):

  - "Leads" (planilha do Funil, SPREADSHEET_ID_FUNIL): fonte UNICA de leads
    (nao ha aba "Conversas" nesse cliente). Cada linha ja vem com a
    atribuicao de campanha/conjunto/anuncio pronta via utm_campaign/
    utm_medium/utm_content — que chegam identicos a Campaign Name/Ad Set
    Name/Ad Name do Meta Ads.
  - "Vendas" (mesma planilha do Funil): compradores. Cruza com Leads por
    lead_id (FK direta); quando lead_id vem vazio, cai no fallback por
    TELEFONE canonico (DDI "55" e 9o digito do celular, presentes ou nao).
  - "Pagina 1" (planilha Meta Ads, SPREADSHEET_ID_META): investimento,
    impressoes, cliques e landing page views do gerenciador.

Criterio de Lead Qualificado (MQL): coluna "classificacao" (coluna O da aba
Leads) == "QUALIFICADO" (nao-qualificado = "DESQUALIFICADO").

Este script apenas LE as planilhas (export CSV publico, buscado por NOME da
aba — sem depender de gid) e emite os REGISTROS BRUTOS (leads[], meta[] e
sales[]) dentro do HTML. sales[] tem um registro POR COMPRA (nunca agregado
por lead/telefone), com a DATA REAL da compra ("pago_em") — camp/adset/ad
vem do lead de origem (por lead_id ou, na ausencia, pelo 1o lead daquele
telefone), nunca a data da compra e' trocada pela do lead. Todos os filtros,
agregacoes, KPIs, tabelas e graficos sao calculados no navegador (client-side
em app.js). Nunca escreve nada de volta nas planilhas.

Teste local: --leads-file / --meta-file / --sales-file apontando para CSVs
baixados (o sandbox do agente nao alcanca docs.google.com; o runner do
GitHub Actions alcanca).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

# Planilha do Funil (Leads + Vendas) — cliente nao usa gid, busca por nome de aba.
SPREADSHEET_ID_FUNIL = "1j3EQE4zbRlUVAKyDPTmlnTDP0Jlvw-enQyMPR2LXjfk"
SHEET_LEADS = "Leads"
SHEET_VENDAS = "Vendas"
# CRM comercial (mesma planilha): lead do CRM -> lead do funil (marketing_lead_id
# = Leads.id) e histórico de etapas. Só conta o funil do produto (metodo_ral).
SHEET_COM_LEADS = "Comercial_Leads"
SHEET_COM_ETAPAS = "Comercial_Etapas"
SHEET_COM_PRESENCA = "Comercial_Presenca"
COM_FUNIL = "metodo_ral"
# Vendas que contam: produto da Formação, pagas a partir do início do funil.
VENDA_PRODUTO = "formacao"
FUNNEL_START = "2026-08-28"
# Planilha do Meta Ads (separada da planilha do Funil).
SPREADSHEET_ID_META = "1xb5itNu9_No6keCKHyzG7qIPobT46BqfmJ_rP0v4h8c"
SHEET_META = "Página 1"
# Campanha de captação de seguidores (mesma planilha da Meta). Colunas da
# Adveronix + 2 preenchidas à mão: Seguidores (ganhos no dia) e Custo por
# seguidor (ignorada: a dash calcula gasto ÷ seguidores, com o imposto).
SHEET_SEG = "Seguidores IG"
# headers=1: sem ele o gviz funde o cabeçalho com a 1ª linha quando a aba tem
# muitas colunas vazias (acontecia na Comercial_Leads).
EXPORT_URL = "https://docs.google.com/spreadsheets/d/{sid}/gviz/tq?tqx=out:csv&headers=1&sheet={sheet}"

# Identificação do cliente/conta (usada só em textos/relatórios — não afeta o cruzamento de dados).
CLIENT_NAME = "Lucas Nigro"
MAIN_PRODUCT = "Funil de Sessão Estratégica"
# Prefixo comum a TODAS as campanhas da conta (usado para agrupar campanhas no
# dashboard, sem filtrar por sub-funil/etapa — ex. campanhas "E2-CAP" continuam
# entrando normalmente, só o prefixo "RAL" é exigido).
MAIN_PRODUCT_PREFIX = "RAL"

BRT = timezone(timedelta(hours=-3))   # horario de Brasilia (exibicao)
TAX_FACTOR = 1.1385   # imposto de 13,85% sobre o gasto de mídia (Meta Ads)

# --------------------------------------------------------------------------- #
# Regras da aba Relatório (Top/Piores anúncios)
# --------------------------------------------------------------------------- #
# Amostra mínima para julgar um anúncio como "vencedor" ou "ruim". Abaixo disso
# ele entra como "Em observação" (dado insuficiente) — nunca é classificado só
# porque teve 1 resultado com pouco investimento. Ajuste conforme o ticket/CAC.
SAMPLE_MIN_SPEND = 100.0   # gasto mínimo (R$) para amostra relevante
SAMPLE_MIN_MQLS = 3        # MQLs mínimos para julgar qualidade profunda
TOP_ADS_N = 10             # nº de linhas em Top / Piores anúncios

# Metas & parâmetros da conta (DEFAULTS do painel editável da aba Relatório).
# São só o valor inicial: o usuário edita no navegador (persistido em
# localStorage) e as tabelas de anúncios recoram CPMQL/CAC e reavaliam a
# amostra ao vivo. None = "meta não definida" (métrica aparece sem cor até o
# gestor preencher).
META_CPMQL = None          # meta de CPMQL (R$/MQL); None = não definida
META_CAC = None            # meta de CAC (R$/venda); None = não definida
VOLUME_MIN_AMOSTRAL = SAMPLE_MIN_MQLS  # conversões (MQLs) mínimas p/ amostra confiável
N_DIAS_CORTE = 5           # dias consecutivos acima do teto p/ considerar corte


# --------------------------------------------------------------------------- #
# Leitura
# --------------------------------------------------------------------------- #
def fetch_csv(url: str) -> list[list[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "dash-ral-bot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return list(csv.reader(io.StringIO(raw)))


def read_csv_file(path: str) -> list[list[str]]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.reader(f))


def load_rows(url: str, local: str | None) -> list[list[str]]:
    return read_csv_file(local) if local else fetch_csv(url)


def sheet_url(sid: str, sheet: str) -> str:
    return EXPORT_URL.format(sid=sid, sheet=urllib.parse.quote(sheet))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str | None) -> str:
    return strip_accents((s or "").strip().lower())


def to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v).strip())
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_date(v: str) -> str | None:
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_date_brt(v: str) -> str | None:
    """Como parse_date(), mas para timestamps COM FUSO (ISO-8601, ex.
    "2026-09-01T01:25:15+00:00" ou terminado em "Z") — CONVERTE para o fuso de
    Brasília (BRT, UTC-3) antes de extrair a data. Essencial pra bater com o
    Meta Ads, que reporta "Day" no fuso local da conta (BRT): um lead/venda
    registrado às 23h de um dia em BRT já é madrugada do dia seguinte em UTC,
    e sem essa conversão ele "vaza" pro dia errado (e pro período errado nos
    filtros). Strings sem hora/fuso (datas puras, ex. o "Day" do Meta) não têm
    o que converter — cai no parse_date() normal."""
    if not v:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone(BRT).strftime("%Y-%m-%d")
    except ValueError:
        pass
    return parse_date(s)


def is_test_lead(rowtext: str) -> bool:
    return "<test lead" in rowtext.lower()


def is_yes(v: str | None) -> bool:
    return norm(v) in ("sim", "s", "yes", "true", "1")


def is_qualificado(v: str | None) -> bool:
    """Critério de MQL: coluna "classificacao" (coluna O da aba Leads) == "QUALIFICADO"."""
    return norm(v) == "qualificado"


def pretty_bucket(v: str) -> str:
    s = (v or "").strip()
    return s if s else "Sem resposta"


def mask_email(e: str) -> str:
    e = (e or "").strip()
    if "@" not in e:
        return "—"
    user, dom = e.split("@", 1)
    keep = user[:2] if len(user) > 2 else user[:1]
    return f"{keep}****@{dom}"


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p or "")
    return f"…{digits[-4:]}" if len(digits) >= 4 else "—"


def norm_phone(p: str) -> str:
    return re.sub(r"\D", "", p or "")


def canon_phone(p: str) -> str:
    """Chave CANÔNICA de telefone p/ cruzar Vendas × Leads (fallback quando não
    há lead_id), robusta às 2 variações que fariam o mesmo número não bater
    quando comparado só por dígitos (norm_phone):
      - DDI "55" presente de um lado e ausente do outro
        (5511988887777 vs 11988887777);
      - 9º dígito do celular presente/ausente
        (11988887777 vs 1188887777).
    Estratégia: remove o DDI 55 (quando sobra DDD+número) e usa DDD (2 díg.) +
    ÚLTIMOS 8 DÍGITOS — que é o mesmo com ou sem o 9. Devolve chave de 10 díg.
    (DDD+8). Números curtos/estrangeiros (< 10 díg. após limpar) voltam como
    estão, pra não colidir à toa."""
    d = norm_phone(p)
    if len(d) > 11 and d.startswith("55"):
        d = d[2:]            # tira DDI do Brasil, sobrando DDD + local
    if len(d) >= 10:
        return d[:2] + d[-8:]   # DDD + últimos 8 (drop do 9º dígito, se houver)
    return d


def first_last_initial(name: str) -> str:
    parts = (name or "").strip().split()
    if not parts:
        return "—"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][:1]}."


def valid_utm(campaign: str) -> bool:
    c = norm(campaign)
    return bool(c) and c not in ("-", "—", "nao encontrado")


# --------------------------------------------------------------------------- #
# Indexacao das colunas
# --------------------------------------------------------------------------- #
def header_index(header, wanted, fallback):
    """Casa cada alias com uma coluna do cabeçalho. Exact match tem prioridade
    sobre substring match (evita, por ex., o alias "pago" casar com a coluna
    "pago_em" antes de chegar na coluna "pago" de fato)."""
    idx = {}
    hn = [norm(h) for h in header]
    for key, aliases in wanted.items():
        norm_aliases = [norm(a) for a in aliases]
        found = None
        for a in norm_aliases:
            for i, h in enumerate(hn):
                if h == a:
                    found = i
                    break
            if found is not None:
                break
        if found is None:
            for a in norm_aliases:
                if not a:
                    continue
                for i, h in enumerate(hn):
                    if a in h:
                        found = i
                        break
                if found is not None:
                    break
        idx[key] = found if found is not None else fallback.get(key)
    return idx


def cell(row, i):
    if i is None or i < 0 or i >= len(row):
        return ""
    return (row[i] or "").strip()


# --------------------------------------------------------------------------- #
# Vendas -> lista de compras (uma entrada por linha, nunca agregada)
# --------------------------------------------------------------------------- #
def build_purchases(sales_rows):
    """Vendas da aba Vendas (Eduzz) que contam na dash: pagamento confirmado
    (`pago` == "sim"), produto da Formação (`VENDA_PRODUTO`) e pagas a partir
    do início do funil (`FUNNEL_START` — tira a venda de 26/08, anterior ao
    funil). O produto de teste (valor 0) cai no filtro de produto. Uma entrada
    por linha: [{"lead_id","phone","d","fat","receita","nm"}, ...]."""
    header = sales_rows[0] if sales_rows else []
    idx = header_index(
        header,
        {"lead_id": ["lead_id"], "phone": ["whatsapp", "telefone"], "date": ["pago_em", "data"],
         "valor": ["valor", "faturamento"], "name": ["comprador", "nome"], "pago": ["pago", "status"],
         "produto": ["produto"]},
        {"lead_id": 12, "phone": 6, "date": 1, "valor": 7, "name": 4, "pago": 3, "produto": 9},
    )
    out = []
    for row in sales_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        if not is_yes(cell(row, idx["pago"])):
            continue
        d = parse_date_brt(cell(row, idx["date"]))
        if VENDA_PRODUTO not in norm(cell(row, idx["produto"])) or not d or d < FUNNEL_START:
            continue
        valor = to_float(cell(row, idx["valor"]))
        out.append({
            "lead_id": cell(row, idx["lead_id"]),
            "phone": norm_phone(cell(row, idx["phone"])),
            "d": d,
            "fat": valor,
            "receita": valor,
            "nm": cell(row, idx["name"]),
        })
    return out


def log_unmatched_sales(matched: int, total: int, unmatched: list[dict]):
    """Diagnóstico (stderr): vendas sem lead do funil correspondente. Elas
    contam no total (Visão Geral), sem campanha/anúncio."""
    print(f"  vendas: {total} (Formação, pagas) | atribuídas a campanha: {matched}", file=sys.stderr)
    for p in unmatched:
        ph = p["phone"]
        print(f"    - sem vínculo: {p['d'] or '?'}  {first_last_initial(p['nm'])}  tel …{ph[-4:] if len(ph) >= 4 else ph}",
              file=sys.stderr)


# --------------------------------------------------------------------------- #
# Processamento -> registros brutos
# --------------------------------------------------------------------------- #
REUNIAO_ETAPAS = ("reuniao_agendada", "proposta_enviada", "fechado")
PROPOSTA_ETAPAS = ("proposta_enviada", "fechado")
# "desconhecida" = histórico importado em massa (data da importação, não da
# mudança de etapa) — não conta, igual ao painel do Moisés.
EVENTO_VALIDO = ("real", "inferida")
SEM_VINCULO = {"src": "sem_vinculo", "camp": "(sem campanha)", "adset": "(sem conjunto)", "ad": "(sem anúncio)"}


def active_keys(presenca_rows):
    """Chaves "<aba>:<registro_id>" com ativo == 1 na Comercial_Presenca (a
    planilha nunca apaga linha). None = sem a aba -> não filtra."""
    if not presenca_rows:
        return None
    idx = header_index(presenca_rows[0], {"chave": ["chave"], "ativo": ["ativo"]}, {"chave": 0, "ativo": 3})
    return {cell(r, idx["chave"]) for r in presenca_rows[1:] if cell(r, idx["ativo"]) == "1"}


def build_commercial(com_leads_rows, com_etapas_rows, presenca_rows, id_attrib, phone_attrib):
    """Reuniões e propostas do CRM comercial em MODO COORTE: um registro por
    lead por etapa alcançada, datado no dia em que o lead ENTROU (não no dia
    da etapa): [{d, src, camp, adset, ad, ag|pr|lc: 1}, ...].

    - Só funil COM_FUNIL, só registros ativos (Comercial_Presenca) e só
      eventos `inferida` real/inferida (EVENTO_VALIDO).
    - Regra de 16/10: proposta ou fechado => teve reunião; fechado => proposta.
    - Lead do CRM -> lead do funil por `marketing_lead_id` (= Leads.id), na
      falta pelo telefone canônico. Ligado: data e campanha do lead da aba
      Leads. Sem ligação: entra no total (SEM_VINCULO), datado pela 1ª
      entrada no funil, e vira também um registro `lc` (lead só do CRM).
    - Lead com data de entrada anterior a FUNNEL_START fica de fora."""
    if not com_leads_rows or not com_etapas_rows:
        return []
    ativos = active_keys(presenca_rows)

    def ativo(aba, rid):
        return ativos is None or f"{aba}:{rid}" in ativos

    cidx = header_index(
        com_leads_rows[0],
        {"id": ["lead_id"], "mk": ["marketing_lead_id"], "phone": ["whatsapp"]},
        {"id": 0, "mk": 1, "phone": 4},
    )
    crm = {cell(r, cidx["id"]): r for r in com_leads_rows[1:]
           if cell(r, cidx["id"]) and ativo(SHEET_COM_LEADS, cell(r, cidx["id"]))}

    eidx = header_index(
        com_etapas_rows[0],
        {"ev": ["evento_id"], "id": ["lead_id"], "funil": ["funil_codigo"], "etapa": ["etapa_codigo"],
         "d": ["entrou_em"], "inf": ["inferida"]},
        {"ev": 0, "id": 1, "funil": 3, "etapa": 6, "d": 8, "inf": 10},
    )
    first: dict[str, str] = {}
    stages: dict[str, set] = {}
    for row in com_etapas_rows[1:]:
        lid = cell(row, eidx["id"])
        if not lid or cell(row, eidx["funil"]) != COM_FUNIL or not ativo(SHEET_COM_ETAPAS, cell(row, eidx["ev"])):
            continue
        d = parse_date_brt(cell(row, eidx["d"]))
        if d and (lid not in first or d < first[lid]):
            first[lid] = d
        st = stages.setdefault(lid, set())
        if norm(cell(row, eidx["inf"])) in EVENTO_VALIDO:
            st.add(cell(row, eidx["etapa"]))

    # vários leads do CRM podem apontar pro mesmo lead do funil -> junta por chave
    per_key: dict[str, dict] = {}
    for lid, st in stages.items():
        row = crm.get(lid)
        attrib = None
        if row is not None:
            mk = cell(row, cidx["mk"])
            attrib = id_attrib.get(mk) if mk else None
            if attrib is None:
                attrib = phone_attrib.get(canon_phone(cell(row, cidx["phone"])))
        if attrib is not None:
            k, base, d, linked = attrib["key"], {f: attrib[f] for f in ("src", "camp", "adset", "ad")}, attrib["d"], True
        else:
            k, base, d, linked = f"crm:{lid}", dict(SEM_VINCULO), first.get(lid), False
        cur = per_key.setdefault(k, {"base": base, "d": d, "st": set(), "linked": linked})
        cur["st"] |= st
        if d and (cur["d"] is None or d < cur["d"]):
            cur["d"] = d

    out = []
    antes = 0
    for cur in per_key.values():
        if not cur["d"] or cur["d"] < FUNNEL_START:   # lead do CRM anterior ao funil
            antes += 1
            continue
        rec = {**cur["base"], "d": cur["d"]}
        if not cur["linked"]:
            out.append({**rec, "lc": 1})
        if cur["st"] & set(REUNIAO_ETAPAS):
            out.append({**rec, "ag": 1})
        if cur["st"] & set(PROPOSTA_ETAPAS):
            out.append({**rec, "pr": 1})
    print(f"  comercial ({COM_FUNIL}): {len(per_key)} leads ({sum(1 for c in per_key.values() if c['linked'])} ligados à aba Leads) | "
          f"anteriores a {FUNNEL_START} (fora): {antes} | "
          f"reuniões: {sum(r.get('ag', 0) for r in out)} | propostas: {sum(r.get('pr', 0) for r in out)}",
          file=sys.stderr)
    return out


def build_followers(seg_rows):
    """Aba "Seguidores IG": [{d, camp, adset, ad, sp, im, cl, seg}] por dia/anúncio.
    `seg` = seguidores ganhos (preenchido à mão); célula vazia = não preenchido
    (None), diferente de 0 — o custo por seguidor só usa o gasto das linhas
    preenchidas. Linhas sem gasto, sem impressão e sem seguidor são puladas."""
    if not seg_rows:
        return []
    idx = header_index(
        seg_rows[0],
        {"day": ["day", "data"], "campaign": ["campaign name"], "adset": ["ad set name"], "ad": ["ad name"],
         "impr": ["impressions"], "clicks": ["link clicks"], "spent": ["amount spent"], "seg": ["seguidores"]},
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "impr": 4, "clicks": 5, "spent": 6, "seg": 7},
    )
    out = []
    for row in seg_rows[1:]:
        d = parse_date(cell(row, idx["day"]))
        if not d:
            continue
        raw = cell(row, idx["seg"])
        seg = int(round(to_float(raw))) if raw else None
        sp, im = round(to_float(cell(row, idx["spent"])), 4), to_float(cell(row, idx["impr"]))
        if not sp and not im and not seg:
            continue
        out.append({
            "d": d,
            "camp": cell(row, idx["campaign"]) or "(sem campanha)",
            "adset": cell(row, idx["adset"]) or "(sem conjunto)",
            "ad": cell(row, idx["ad"]) or "(sem anúncio)",
            "sp": sp, "im": im, "cl": to_float(cell(row, idx["clicks"])),
            "seg": seg,
        })
    print(f"  seguidores: {len(out)} linhas | gasto R$ {sum(r['sp'] for r in out):,.2f} | "
          f"seguidores {sum(r['seg'] or 0 for r in out)} | linhas sem preencher {sum(1 for r in out if r['seg'] is None)}",
          file=sys.stderr)
    return out


def process(leads_rows, meta_rows, sales_rows, com_leads_rows=None, com_etapas_rows=None, presenca_rows=None,
            seg_rows=None):
    lheader = leads_rows[0] if leads_rows else []
    lidx = header_index(
        lheader,
        {"id": ["id"], "created": ["criado_em"], "phone": ["whatsapp"], "name": ["nome"],
         "qualif": ["classificacao"], "campaign": ["utm_campaign"], "adset": ["utm_medium"],
         "ad": ["utm_content"], "bucket": ["atende_empresas"], "source": ["utm_source"]},
        {"id": 0, "created": 1, "phone": 3, "name": 2, "qualif": 14, "campaign": 7, "adset": 6, "ad": 8,
         "bucket": 10, "source": 5},
    )

    leads = []
    # Atribuicao do ANUNCIO/campanha de uma venda: preferencialmente pelo
    # lead_id (chave direta Vendas.lead_id -> Leads.id); na ausencia, pelo 1o
    # lead (mais antigo) daquele telefone (mesma logica de "1a conversa" do
    # template generico, aqui aplicada sobre a propria aba Leads).
    rows_sorted = sorted(
        [r for r in leads_rows[1:] if any((c or "").strip() for c in r)],
        key=lambda r: parse_date_brt(cell(r, lidx["created"])) or "",
    )
    id_attrib: dict[str, dict] = {}
    phone_attrib: dict[str, dict] = {}
    for row in rows_sorted:
        if is_test_lead(" ".join(str(c) for c in row)):
            continue
        campaign_raw = cell(row, lidx["campaign"])
        campaign_valid = valid_utm(campaign_raw)
        # utm_source "chatgpt-ads"/"chatgpt" = ChatGPT Ads: página própria na
        # dash, sem gasto (não há planilha de mídia do ChatGPT) e fora da de Meta.
        # Meta só com utm_source da Meta (ou vazio); outra origem com campanha
        # preenchida (ex.: lead de teste "adryan gpt") vira "outros".
        source = norm(cell(row, lidx["source"]))
        if source.startswith("chatgpt"):
            src = "chatgpt"
        elif not campaign_valid:
            src = "org"
        elif not source or source.startswith(("meta", "facebook", "fb", "instagram", "ig")):
            src = "meta"
        else:
            src = "outros"
        camp = campaign_raw if campaign_valid else "(sem campanha)"
        adset = cell(row, lidx["adset"]) if campaign_valid else "(sem conjunto)"
        ad = cell(row, lidx["ad"]) if campaign_valid else "(sem anúncio)"
        lead_date = parse_date_brt(cell(row, lidx["created"]))
        lead_id = cell(row, lidx["id"])
        phone = canon_phone(cell(row, lidx["phone"]))
        attrib = {"src": src, "camp": camp, "adset": adset, "ad": ad, "d": lead_date, "key": lead_id or phone}
        if lead_id:
            id_attrib[lead_id] = attrib
        if phone and phone not in phone_attrib:
            phone_attrib[phone] = attrib
        bucket = pretty_bucket(cell(row, lidx["bucket"]))
        leads.append({
            "d": lead_date,
            "src": src,
            "plat": {"meta": "ig", "chatgpt": "gpt"}.get(src, "—"),
            "camp": camp,
            "adset": adset,
            "ad": ad,
            "prof": bucket,
            "bucket": bucket,
            "q": 1 if is_qualificado(cell(row, lidx["qualif"])) else 0,
            "utm": 1 if campaign_valid else 0,
            "nm": first_last_initial(cell(row, lidx["name"])),
            "em": "—",
            "ph": mask_phone(cell(row, lidx["phone"])),
        })

    # Vendas: um registro POR COMPRA da aba Vendas (filtros em build_purchases).
    # Atribuição por lead_id (= Leads.id), na falta pelo telefone canônico.
    purchases = build_purchases(sales_rows)
    sales = []
    matched = 0
    unmatched = []
    for p in purchases:
        attrib = id_attrib.get(p["lead_id"]) if p["lead_id"] else None
        if attrib is None:
            attrib = phone_attrib.get(canon_phone(p["phone"]))
        # modo coorte: venda ligada conta no dia em que o lead entrou; sem
        # ligação conta no total, sem campanha, na data do pagamento.
        if attrib is None:
            unmatched.append(p)
            base, d = SEM_VINCULO, p["d"]
        else:
            matched += 1
            base, d = attrib, attrib["d"] or p["d"]
        sales.append({
            "d": d,
            "src": base["src"],
            "camp": base["camp"],
            "adset": base["adset"],
            "ad": base["ad"],
            "vendas": 1,
            "fat": round(p["fat"], 2),
            "receita": round(p["receita"], 2),
        })

    log_unmatched_sales(matched, len(purchases), unmatched)
    com = build_commercial(com_leads_rows, com_etapas_rows, presenca_rows, id_attrib, phone_attrib)
    seg = build_followers(seg_rows)

    mheader = meta_rows[0] if meta_rows else []
    midx = header_index(
        mheader,
        {"day": ["day", "data"], "campaign": ["campaign name", "campaign"], "adset": ["ad set name", "adset"],
         "ad": ["ad name"], "spent": ["amount spent", "valor gasto", "gasto"], "impr": ["impressions", "impress"],
         "clicks": ["link clicks", "clicks", "cliques"], "leads": ["leads"],
         "pv": ["landing page views", "page views", "pageviews"],
         # Conta não tem "Adds to Cart"/"Initiate Checkout" no export atual —
         # fica 0/"-" até o cliente adicionar essa coluna na planilha do Meta.
         "chk": ["adds to cart", "add to cart", "initiate checkout", "checkouts iniciados", "checkouts"],
         # Link do criativo — coluna opcional, ainda não existe no export do
         # cliente. Sem ela, o Link nas tabelas Top/Piores vira "—".
         "link": ["creative instagram permalink", "instagram permalink", "permalink",
                  "creative link", "link do anuncio", "link do criativo"]},
        {"day": 0, "campaign": 1, "adset": 2, "ad": 3, "spent": 7, "impr": 4, "clicks": 5, "leads": None, "pv": 6},
    )

    meta = []
    # Anúncio (nome) -> 1 permalink do criativo, quando existir a coluna.
    ad_links = {}
    for row in meta_rows[1:]:
        if not any((c or "").strip() for c in row):
            continue
        ad = cell(row, midx["ad"]) or "(sem anúncio)"
        link = cell(row, midx["link"])
        if link and ad not in ad_links:
            ad_links[ad] = link
        meta.append({
            "d": parse_date(cell(row, midx["day"])),
            "camp": cell(row, midx["campaign"]) or "(sem campanha)",
            "adset": cell(row, midx["adset"]) or "(sem conjunto)",
            "ad": ad,
            "sp": round(to_float(cell(row, midx["spent"])), 4),
            "im": to_float(cell(row, midx["impr"])),
            "cl": to_float(cell(row, midx["clicks"])),
            "pv": to_float(cell(row, midx["pv"])),
            "ck": to_float(cell(row, midx["chk"])),
            "ml": to_float(cell(row, midx["leads"])),
        })

    dates = sorted({d for d in (
        [l["d"] for l in leads if l["d"]] + [m["d"] for m in meta if m["d"]] + [s["d"] for s in sales if s["d"]]
        + [c["d"] for c in com if c["d"]] + [r["d"] for r in seg]
    )})
    now_brt = datetime.now(BRT)
    return {
        "build": {
            "generated_at_brt": now_brt.strftime("%d/%m/%Y %H:%M"),
            "build_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
            "today": now_brt.strftime("%Y-%m-%d"),
            "date_min": dates[0] if dates else None,
            "date_max": dates[-1] if dates else None,
            "tax_factor": TAX_FACTOR,
            # config da aba Relatório (lida pelo front)
            "sample_min_spend": SAMPLE_MIN_SPEND,
            "sample_min_mqls": SAMPLE_MIN_MQLS,
            "top_ads_n": TOP_ADS_N,
            # metas & parâmetros (defaults do painel editável; None = não definida)
            "meta_cpmql": META_CPMQL,
            "meta_cac": META_CAC,
            "volume_min_amostral": VOLUME_MIN_AMOSTRAL,
            "n_dias_corte": N_DIAS_CORTE,
        },
        "leads": leads,
        "meta": meta,
        "sales": sales,
        # Agendamentos/propostas do CRM comercial (build_commercial).
        "com": com,
        # Campanha de captação de seguidores (aba Seguidores IG).
        "seg": seg,
        # Anúncio -> permalink do criativo (aba Relatório).
        "ad_links": ad_links,
        # Insights de Tráfego (texto pré-escrito, lido de relatorios.json). Preenchido
        # em main() via load_briefings(); fica {} se relatorios.json não existir.
        "briefings": {},
    }


# --------------------------------------------------------------------------- #
# Insights de Tráfego (aba Relatório)
# --------------------------------------------------------------------------- #
def load_briefings(path: str) -> dict:
    """Lê build/relatorios.json. Estrutura:
        {"generated_at": "...", "periodos": {"<preset>": {"html": "..."}, ...}}
    Retorna o dict inteiro (ou {} se o arquivo não existir/for inválido).
    A geração NÃO acontece aqui — este build só lê o texto já pronto, sem
    chamar nenhuma API (custo zero no build/no navegador)."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (ValueError, OSError):
        return {}


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render(data, template_path):
    # A dashboard e montada a partir de arquivos separados (visual x logica):
    #   template.html          -> esqueleto HTML (placeholders __STYLES__/__APP_JS__)
    #   identidade-visual.css  -> TODAS as cores (edite aqui p/ mexer so em cor)
    #   estilos.css            -> layout/componentes
    #   app.js                 -> logica + renderizacao
    # Esta funcao so COSTURA os arquivos e injeta os dados; nao altera nada deles.
    base = os.path.dirname(os.path.abspath(template_path))

    def readf(name):
        with open(os.path.join(base, name), "r", encoding="utf-8") as f:
            return f.read()

    with open(template_path, "r", encoding="utf-8") as f:
        tpl = f.read()
    styles = readf("identidade-visual.css") + "\n" + readf("estilos.css")
    tpl = tpl.replace("__STYLES__", styles)
    tpl = tpl.replace("__APP_JS__", readf("app.js"))
    tpl = tpl.replace("__DATA_JSON__", json.dumps(data, ensure_ascii=False))
    tpl = tpl.replace("__BUILD_ID__", data["build"]["build_id"])
    tpl = tpl.replace("__GENERATED_BRT__", data["build"]["generated_at_brt"])
    return tpl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leads-file", help="CSV local da aba Leads (fonte única de leads)")
    ap.add_argument("--meta-file", help="CSV local da aba Página 1 (Meta Ads)")
    ap.add_argument("--sales-file", help="CSV local da aba Vendas (Compradores)")
    ap.add_argument("--com-leads-file", help="CSV local da aba Comercial_Leads")
    ap.add_argument("--com-etapas-file", help="CSV local da aba Comercial_Etapas")
    ap.add_argument("--presenca-file", help="CSV local da aba Comercial_Presenca")
    ap.add_argument("--seg-file", help="CSV local da aba Seguidores IG (planilha da Meta)")
    ap.add_argument("--template", default="build/template.html")
    ap.add_argument("--out", default="dist/index.html")
    args = ap.parse_args()

    leads_rows = load_rows(sheet_url(SPREADSHEET_ID_FUNIL, SHEET_LEADS), args.leads_file)
    sales_rows = load_rows(sheet_url(SPREADSHEET_ID_FUNIL, SHEET_VENDAS), args.sales_file)
    meta_rows = load_rows(sheet_url(SPREADSHEET_ID_META, SHEET_META), args.meta_file)
    com_leads_rows = load_rows(sheet_url(SPREADSHEET_ID_FUNIL, SHEET_COM_LEADS), args.com_leads_file)
    com_etapas_rows = load_rows(sheet_url(SPREADSHEET_ID_FUNIL, SHEET_COM_ETAPAS), args.com_etapas_file)
    presenca_rows = load_rows(sheet_url(SPREADSHEET_ID_FUNIL, SHEET_COM_PRESENCA), args.presenca_file)
    seg_rows = load_rows(sheet_url(SPREADSHEET_ID_META, SHEET_SEG), args.seg_file)

    data = process(leads_rows, meta_rows, sales_rows, com_leads_rows, com_etapas_rows, presenca_rows, seg_rows)

    # Insights de Tráfego (texto pré-escrito) — lidos do arquivo versionado ao
    # lado do template. Sem chamada de API no build.
    briefings_path = os.path.join(os.path.dirname(os.path.abspath(args.template)), "relatorios.json")
    data["briefings"] = load_briefings(briefings_path)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render(data, args.template))

    b = data["build"]
    q = sum(l["q"] for l in data["leads"])
    vd = sum(s["vendas"] for s in data["sales"])
    fat = sum(s["fat"] for s in data["sales"])
    print("== build ok ==", file=sys.stderr)
    print(f"  periodo   : {b['date_min']} -> {b['date_max']}", file=sys.stderr)
    print(f"  leads     : {len(data['leads'])}  MQLs (qualificados): {q}", file=sys.stderr)
    print(f"  vendas    : {vd}  faturamento: R$ {fat:,.2f}", file=sys.stderr)
    print(f"  meta      : {len(data['meta'])} linhas", file=sys.stderr)
    print(f"  out       : {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
