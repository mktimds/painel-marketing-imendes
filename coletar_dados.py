#!/usr/bin/env python3
"""
Coleta os números do Painel de Marketing IMendes e grava dados.json.

Os dados saem POR DIA (últimos DIAS_HISTORICO dias) para o painel somar qualquer
período escolhido no navegador. O alcance do Meta (pessoas únicas) não pode ser
somado dia a dia, então é coletado pronto para os períodos fixos (presets).

Fontes (cada uma só roda se as credenciais existirem; senão o bloco sai com
status "pendente" e o painel mostra o aviso, sem inventar número):

  META_ACCESS_TOKEN                      Meta Ads (Graph API)
  HUBSPOT_TOKEN                          HubSpot (app privado, leitura)
  GADS_CLIENT_ID,
  GADS_CLIENT_SECRET, GADS_REFRESH_TOKEN,
  GADS_CUSTOMER_ID [, GADS_LOGIN_CUSTOMER_ID]   Google Ads API
  GA4_SERVICE_ACCOUNT_JSON               GA4 (cliques no WhatsApp do site)

Só usa a biblioteca padrão do Python, exceto o GA4 (precisa de google-auth).
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

FUSO = dt.timezone(dt.timedelta(hours=-3))  # America/Sao_Paulo (sem horário de verão)
DIAS_HISTORICO = int(os.environ.get("DIAS_HISTORICO", "180"))

META_API = "https://graph.facebook.com/v23.0"
META_CONTAS = [c.strip() for c in os.environ.get(
    "META_AD_ACCOUNTS",
    "act_1248772976109746,act_3464964433774316,act_704326994947485,act_996622288759693",
).split(",") if c.strip()]
META_LEAD_FORM = "onsite_conversion.lead_grouped"                       # formulário instantâneo
META_LEAD_SITE = "offsite_conversion.fb_pixel_lead"                     # evento Lead do pixel no site
META_CONVERSA = "onsite_conversion.messaging_conversation_started_7d"   # conversas iniciadas
# Dias em que o evento Lead do pixel disparou por engano (snippet WPCode mandava Lead em
# clique de WhatsApp/CTA; corrigido em 04/11/2026). Os leads de pixel desses dias são zerados
# e o total descontado vai junto para o painel mostrar o aviso.
META_PIXEL_DIAS_INVALIDOS = ("2026-11-03", "2026-11-04")

HUBSPOT_API = "https://api.hubapi.com"
PIPELINE_PRE_VENDAS = "890773148"
ETAPAS_PRE_VENDAS = {
    "1343038266": "Lead recebido",
    "1343038268": "Contato realizado",
    "1343038270": "Lead qualificado (SQL)",
    "1343038271": "Desqualificado",
    "1342981669": "Perdido",
}
ETAPA_SQL = "1343038270"
FONTES_HUBSPOT = {  # hs_analytics_source (Original Traffic Source)
    "PAID_SOCIAL": "Redes sociais pagas",
    "PAID_SEARCH": "Pesquisa paga",
    "ORGANIC_SEARCH": "Pesquisa orgânica",
    "SOCIAL_MEDIA": "Redes sociais orgânicas",
    "EMAIL_MARKETING": "E-mail marketing",
    "DIRECT_TRAFFIC": "Tráfego direto",
    "REFERRALS": "Referências",
    "AI_REFERRALS": "Referências de IA",
    "OTHER_CAMPAIGNS": "Outras campanhas",
    "OFFLINE": "Offline (importação, manual, integrações)",
    "SEM_ORIGEM": "Sem origem",
}

GA4_PROPRIEDADE = os.environ.get("GA4_PROPERTY_ID", "405901108")
# Evento do Site Kit em cliques em links de contato; link_type diz o tipo (whatsapp, phone, email…).
# A dimensão personalizada "Link Type" (link_type, escopo evento) já existe na propriedade desde 08/2025.
GA4_EVENTO_WHATSAPP = os.environ.get("GA4_EVENTO_WHATSAPP", "contact_link_click")
GA4_TIPO_WHATSAPP = os.environ.get("GA4_TIPO_WHATSAPP", "whatsapp")
# Desde 09/09/2026 o Google não usa mais developer token: o nível de acesso é do projeto do Google Cloud
# (painel-marketing-imendes). GADS_DEVELOPER_TOKEN continua aceito só se existir.
GADS_API_VERSION = os.environ.get("GADS_API_VERSION", "v26")
GADS_CONTA_PADRAO = "7591296003"  # conta iMendes 759-129-6003 (não é segredo)


# --------------------------------------------------------------------------- utilidades

def http_json(url, metodo="GET", corpo=None, headers=None, tentativas=3, form=False):
    dados = None
    headers = dict(headers or {})
    if corpo is not None:
        if form:
            dados = urllib.parse.urlencode(corpo).encode()
        else:
            dados = json.dumps(corpo).encode()
            headers.setdefault("Content-Type", "application/json")
    for i in range(tentativas):
        req = urllib.request.Request(url, data=dados, method=metodo, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            texto = e.read().decode(errors="replace")
            if e.code in (429, 500, 502, 503) and i < tentativas - 1:
                time.sleep(3 * (i + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} em {url.split('?')[0]}: {texto[:400]}")
        except urllib.error.URLError as e:
            if i < tentativas - 1:
                time.sleep(3 * (i + 1))
                continue
            raise RuntimeError(f"Falha de rede em {url.split('?')[0]}: {e}")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def r2(v):
    return round(v, 2)


def presets(hoje):
    ini_mes = hoje.replace(day=1)
    fim_ant = ini_mes - dt.timedelta(days=1)
    return {
        "mes_atual": (ini_mes, hoje),
        "mes_anterior": (fim_ant.replace(day=1), fim_ant),
        "ult7": (hoje - dt.timedelta(days=6), hoje),
        "ult30": (hoje - dt.timedelta(days=29), hoje),
        "ult90": (hoje - dt.timedelta(days=89), hoje),
    }


def bloco_pendente(motivo):
    return {"status": "pendente", "motivo": motivo}


def bloco_erro(e):
    return {"status": "erro", "motivo": str(e)[:500]}


def faixa(p):
    return {"inicio": p[0].isoformat(), "fim": p[1].isoformat()}


# --------------------------------------------------------------------------- Meta Ads

def meta_get(caminho, token, **params):
    params["access_token"] = token
    proxima = f"{META_API}/{caminho}?{urllib.parse.urlencode(params)}"
    saida = []
    while proxima:
        d = http_json(proxima)
        saida.extend(d.get("data", []))
        proxima = d.get("paging", {}).get("next")
    return saida


def acoes(linha):
    return {a["action_type"]: num(a["value"]) for a in linha.get("actions", [])}


def metricas_meta(l):
    """[investimento, impressões, cliques no link, formulário, site, conversas, site descontado]"""
    a = acoes(l)
    site = a.get(META_LEAD_SITE, 0)
    desc = site if l.get("date_start") in META_PIXEL_DIAS_INVALIDOS else 0
    return [r2(num(l.get("spend"))), int(num(l.get("impressions"))), int(a.get("link_click", 0)),
            int(a.get(META_LEAD_FORM, 0)), int(site - desc), int(a.get(META_CONVERSA, 0)), int(desc)]


def coletar_meta(token, hist, pres):
    janela = json.dumps({"since": hist[0].isoformat(), "until": hist[1].isoformat()})
    campanhas, anuncios, ativos = [], [], []
    nomes_campanha = {}
    for conta in META_CONTAS:
        linhas = meta_get(f"{conta}/insights", token, level="campaign", time_increment=1,
                          time_range=janela, limit=500,
                          fields="campaign_id,campaign_name,spend,impressions,actions")
        if linhas:
            ativos.append(conta)
        for l in linhas:
            nomes_campanha[l["campaign_id"]] = l["campaign_name"]
            campanhas.append([l["date_start"], l["campaign_id"]] + metricas_meta(l))
        for l in meta_get(f"{conta}/insights", token, level="ad", time_increment=1,
                          time_range=janela, limit=500,
                          fields="ad_id,ad_name,campaign_id,spend,impressions,actions"):
            anuncios.append([l["date_start"], l["ad_id"]] + metricas_meta(l))

    # nome, campanha e imagem (600px) de cada anúncio que aparece no histórico
    ids = {a[1] for a in anuncios}
    info = {}
    for conta in ativos:
        criativo_do_ad = {}
        for ad in meta_get(f"{conta}/ads", token, fields="id,name,campaign_id,creative{id}", limit=200):
            if ad["id"] in ids:
                info[ad["id"]] = {"nome": ad.get("name"), "campanha": ad.get("campaign_id")}
                criativo_do_ad[ad["id"]] = ad.get("creative", {}).get("id")
        criativos = {c["id"]: c for c in meta_get(
            f"{conta}/adcreatives", token, fields="id,thumbnail_url,image_url,object_type",
            thumbnail_width=600, thumbnail_height=600, limit=200)}
        for ad_id, cid in criativo_do_ad.items():
            c = criativos.get(cid)
            if c:
                info[ad_id]["imagem"] = c.get("image_url") or c.get("thumbnail_url")
                info[ad_id]["tipo"] = c.get("object_type")

    # alcance (pessoas únicas) só para os períodos fixos; soma das contas com veiculação
    alcance = {}
    for chave, p in list(pres.items()) + [("historico", hist)]:
        total = 0
        for conta in ativos:
            for l in meta_get(f"{conta}/insights", token, level="account", fields="reach",
                              time_range=json.dumps({"since": p[0].isoformat(), "until": p[1].isoformat()})):
                total += int(num(l.get("reach")))
        alcance[chave] = total

    colunas = ["data", "id", "investimento", "impressoes", "cliques", "formulario", "site",
               "conversas", "site_descontado"]
    return {
        "status": "ok",
        "fonte": "Meta Graph API",
        "contas": ativos,
        "campanhas_nomes": nomes_campanha,
        "campanhas_diario": {"colunas": colunas, "linhas": campanhas},
        "anuncios": info,
        "anuncios_diario": {"colunas": colunas, "linhas": anuncios},
        "alcance": alcance,
        "alcance_obs": "pessoas únicas, soma das contas" if len(ativos) > 1 else "pessoas únicas",
        "pixel_dias_invalidos": list(META_PIXEL_DIAS_INVALIDOS),
        "pixel_aviso": "O evento Lead do pixel disparava em cliques de WhatsApp/CTA (erro corrigido em 04/11/2026).",
    }


# --------------------------------------------------------------------------- HubSpot

def hs_buscar(token, objeto, filtros, propriedades):
    """Busca paginada. A busca do HubSpot para em 10.000 resultados, por isso quem chama
    divide o período em meses."""
    corpo = {"filterGroups": filtros, "limit": 200, "properties": propriedades,
             "sorts": [{"propertyName": "hs_object_id", "direction": "ASCENDING"}]}
    saida, depois = [], None
    while True:
        if depois:
            corpo["after"] = depois
        d = http_json(f"{HUBSPOT_API}/crm/v3/objects/{objeto}/search", "POST", corpo,
                      {"Authorization": f"Bearer {token}"})
        time.sleep(0.22)  # limite da busca: 5 req/s
        saida += d.get("results", [])
        depois = d.get("paging", {}).get("next", {}).get("after")
        if not depois:
            return saida
        if len(saida) >= 9800:
            raise RuntimeError(f"Mais de 10.000 {objeto} num só bloco; diminua o intervalo")


def ms(data, fim=False):
    momento = dt.datetime.combine(data, dt.time.max if fim else dt.time.min, FUSO)
    return str(int(momento.timestamp() * 1000))


def dia_local(valor):
    if not valor:
        return None
    if valor.isdigit():
        momento = dt.datetime.fromtimestamp(int(valor) / 1000, dt.timezone.utc)
    else:
        momento = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
    return momento.astimezone(FUSO).date().isoformat()


def origem_midia(fonte, detalhe):
    """Qual mídia paga trouxe o registro, pela origem original do HubSpot."""
    detalhe = (detalhe or "").lower()
    if fonte == "PAID_SOCIAL":
        if "linkedin" in detalhe:
            return "linkedin"
        if "facebook" in detalhe or "instagram" in detalhe:
            return "meta"
    if fonte == "PAID_SEARCH":
        return "google"
    return "outro"


def blocos_mensais(ini, fim):
    a = ini
    while a <= fim:
        prox = (a.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield a, min(fim, prox - dt.timedelta(days=1))
        a = prox


def coletar_hubspot(token, hist):
    # contatos criados por dia, origem e sinal de WhatsApp (agregados, sem dados pessoais)
    props_c = ["createdate", "hs_analytics_source", "hs_analytics_source_data_1",
               "canal_de_entrada", "gc_mensagem_whatsapp"]
    contagem = {}
    for a, b in blocos_mensais(*hist):
        for c in hs_buscar(token, "contacts", [{"filters": [
                {"propertyName": "createdate", "operator": "BETWEEN", "value": ms(a), "highValue": ms(b, True)}]}],
                props_c):
            p = c["properties"]
            fonte = p.get("hs_analytics_source") or "SEM_ORIGEM"
            wpp = 1 if (p.get("canal_de_entrada") == "WhatsApp" or p.get("gc_mensagem_whatsapp")) else 0
            chave = (dia_local(p.get("createdate")), fonte,
                     origem_midia(fonte, p.get("hs_analytics_source_data_1")), wpp,
                     p.get("gc_mensagem_whatsapp") or "")
            contagem[chave] = contagem.get(chave, 0) + 1
    contatos = [list(k) + [v] for k, v in sorted(contagem.items())]

    # negócios do pré-vendas criados OU que entraram em SQL no histórico
    entrou_sql = f"hs_v2_date_entered_{ETAPA_SQL}"
    props_d = ["dealname", "createdate", "dealstage", entrou_sql, "canal_de_entrada",
               "hs_analytics_source", "hs_analytics_source_data_1"]
    pv = {"propertyName": "pipeline", "operator": "EQ", "value": PIPELINE_PRE_VENDAS}
    vistos = {}
    for a, b in blocos_mensais(*hist):
        for campo in ("createdate", entrou_sql):
            for d in hs_buscar(token, "deals", [{"filters": [pv, {
                    "propertyName": campo, "operator": "BETWEEN", "value": ms(a), "highValue": ms(b, True)}]}],
                    props_d):
                vistos[d["id"]] = d["properties"]
    negocios = []
    for p in vistos.values():
        dia_sql = dia_local(p.get(entrou_sql))
        negocios.append([
            dia_local(p.get("createdate")), p.get("dealstage"), dia_sql,
            p.get("canal_de_entrada") or "",
            origem_midia(p.get("hs_analytics_source"), p.get("hs_analytics_source_data_1")),
            # nome e hora só para os que viraram SQL (lista "últimas mãos levantadas")
            (p.get("dealname") if dia_sql else None), (p.get(entrou_sql) if dia_sql else None),
        ])
    negocios.sort(key=lambda x: (x[0] or "", x[2] or ""))

    return {
        "status": "ok",
        "fonte": "HubSpot CRM API (portal 51057163)",
        "fontes_rotulos": FONTES_HUBSPOT,
        "etapas": ETAPAS_PRE_VENDAS,
        "etapa_sql": ETAPA_SQL,
        "contatos_diario": {"colunas": ["data", "fonte", "midia", "whatsapp", "gc_mensagem", "contatos"],
                            "linhas": contatos},
        "negocios": {"colunas": ["criado", "etapa", "entrou_sql", "canal", "midia", "nome", "sql_em"],
                     "linhas": negocios},
    }


# --------------------------------------------------------------------------- Google Ads

def gads_token():
    d = http_json("https://oauth2.googleapis.com/token", "POST", {
        "client_id": os.environ["GADS_CLIENT_ID"],
        "client_secret": os.environ["GADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GADS_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, form=True)
    return d["access_token"]


def gads_query(acesso, gaql):
    cid = os.environ.get("GADS_CUSTOMER_ID", GADS_CONTA_PADRAO).replace("-", "")
    headers = {"Authorization": f"Bearer {acesso}"}
    if os.environ.get("GADS_DEVELOPER_TOKEN"):
        headers["developer-token"] = os.environ["GADS_DEVELOPER_TOKEN"]
    if os.environ.get("GADS_LOGIN_CUSTOMER_ID"):
        headers["login-customer-id"] = os.environ["GADS_LOGIN_CUSTOMER_ID"].replace("-", "")
    url = f"https://googleads.googleapis.com/{GADS_API_VERSION}/customers/{cid}/googleAds:search"
    linhas, pagina = [], None
    while True:
        corpo = {"query": gaql}
        if pagina:
            corpo["pageToken"] = pagina
        d = http_json(url, "POST", corpo, headers)
        linhas += d.get("results", [])
        pagina = d.get("nextPageToken")
        if not pagina:
            return linhas


def coletar_google_ads(hist):
    acesso = gads_token()
    quando = f"segments.date BETWEEN '{hist[0].isoformat()}' AND '{hist[1].isoformat()}'"
    m = "metrics.cost_micros, metrics.impressions, metrics.clicks, metrics.conversions"
    met = lambda mm: [r2(num(mm.get("costMicros")) / 1e6), int(num(mm.get("impressions"))),
                      int(num(mm.get("clicks"))), r2(num(mm.get("conversions")))]

    nomes, campanhas = {}, []
    for l in gads_query(acesso, f"SELECT segments.date, campaign.id, campaign.name, "
                                f"campaign.advertising_channel_type, {m} FROM campaign "
                                f"WHERE {quando} AND metrics.impressions > 0"):
        c = l["campaign"]
        nomes[c["id"]] = {"nome": c["name"], "tipo": c.get("advertisingChannelType")}
        campanhas.append([l["segments"]["date"], c["id"]] + met(l["metrics"]))

    palavras = []
    for l in gads_query(acesso, "SELECT segments.date, ad_group_criterion.keyword.text, "
                                f"campaign.id, {m} FROM keyword_view WHERE {quando} AND metrics.impressions > 0"):
        palavras.append([l["segments"]["date"], l["adGroupCriterion"]["keyword"]["text"],
                         l["campaign"]["id"]] + met(l["metrics"]))

    termos = []
    for l in gads_query(acesso, "SELECT segments.date, search_term_view.search_term, "
                                f"{m} FROM search_term_view WHERE {quando} AND metrics.clicks > 0"):
        termos.append([l["segments"]["date"], l["searchTermView"]["searchTerm"]] + met(l["metrics"]))

    col = ["investimento", "impressoes", "cliques", "conversoes"]
    return {"status": "ok", "fonte": "Google Ads API (conta 759-129-6003)", "campanhas_nomes": nomes,
            "campanhas_diario": {"colunas": ["data", "id"] + col, "linhas": campanhas},
            "palavras_diario": {"colunas": ["data", "palavra", "campanha"] + col, "linhas": palavras},
            "termos_diario": {"colunas": ["data", "termo"] + col, "linhas": termos}}


# --------------------------------------------------------------------------- GA4

def coletar_ga4(hist):
    from google.oauth2 import service_account  # pip install google-auth requests
    from google.auth.transport.requests import Request

    info = json.loads(os.environ["GA4_SERVICE_ACCOUNT_JSON"])
    cred = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    cred.refresh(Request())
    corpo = {
        "dateRanges": [{"startDate": hist[0].isoformat(), "endDate": hist[1].isoformat()}],
        "metrics": [{"name": "eventCount"}],
        "dimensions": [{"name": "date"}, {"name": "sessionSource"}, {"name": "sessionMedium"}],
        "dimensionFilter": {"andGroup": {"expressions": [
            {"filter": {"fieldName": "eventName", "stringFilter": {"value": GA4_EVENTO_WHATSAPP}}},
            {"filter": {"fieldName": "customEvent:link_type", "stringFilter": {"value": GA4_TIPO_WHATSAPP}}},
        ]}},
        "limit": 100000,
    }
    d = http_json(f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPRIEDADE}:runReport",
                  "POST", corpo, {"Authorization": f"Bearer {cred.token}"})
    soma, origens = {}, {}
    for r in d.get("rows", []):
        v, fonte, meio = (x["value"] for x in r["dimensionValues"])
        q = int(num(r["metricValues"][0]["value"]))
        chave = (f"{v[:4]}-{v[4:6]}-{v[6:]}", midia_ga4(fonte, meio))
        soma[chave] = soma.get(chave, 0) + q
        orig = (chave[0], f"{fonte} / {meio}")
        origens[orig] = origens.get(orig, 0) + q
    linhas = sorted([d_, m_, q] for (d_, m_), q in soma.items())
    return {"status": "ok",
            "fonte": f"GA4 {GA4_PROPRIEDADE}, evento {GA4_EVENTO_WHATSAPP} com link_type = {GA4_TIPO_WHATSAPP}",
            "diario": {"colunas": ["data", "midia", "cliques"], "linhas": linhas},
            "origens_diario": {"colunas": ["data", "origem", "cliques"],
                               "linhas": sorted([d_, o_, q] for (d_, o_), q in origens.items())}}


def midia_ga4(fonte, meio):
    """Mídia paga pela origem/mídia da sessão (UTMs do gerador-utm.html ou gclid). Sem mídia paga → 'outras'."""
    f, m = (fonte or "").lower(), (meio or "").lower()
    pago = m in ("cpc", "ppc", "paid", "paid_social", "paidsocial", "paid-social") or "paid" in m or m.endswith("ads")
    if f == "google" and m == "cpc":
        return "google"
    if pago and any(x in f for x in ("facebook", "instagram", "meta")) or (pago and f in ("fb", "ig", "an", "msg")):
        return "meta"
    if pago and "linkedin" in f:
        return "linkedin"
    return "outras"


# --------------------------------------------------------------------------- principal

def rodar(nome, func, *args):
    t = time.time()
    try:
        print(f"→ {nome}…", file=sys.stderr)
        r = func(*args)
        print(f"  ✓ {nome} ({time.time() - t:.0f}s)", file=sys.stderr)
        return r
    except Exception as e:  # um canal com erro não derruba o painel inteiro
        print(f"  ✗ {nome}: {e}", file=sys.stderr)
        return bloco_erro(e)


def limpar_segredos():
    """Aceita token colado com o nome na frente (NOME=valor), aspas, espaços ou quebra de linha."""
    for nome in ("META_ACCESS_TOKEN", "HUBSPOT_TOKEN", "GADS_DEVELOPER_TOKEN", "GADS_CLIENT_ID",
                 "GADS_CLIENT_SECRET", "GADS_REFRESH_TOKEN", "GADS_CUSTOMER_ID", "GADS_LOGIN_CUSTOMER_ID"):
        v = os.environ.get(nome)
        if not v:
            continue
        v = v.strip().strip('"').strip("'").strip()
        if v.startswith(nome + "="):
            v = v[len(nome) + 1:].strip().strip('"').strip("'").strip()
        os.environ[nome] = v


def main():
    limpar_segredos()
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados.json"))
    args = ap.parse_args()

    agora = dt.datetime.now(FUSO)
    hoje = agora.date()
    hist = (hoje - dt.timedelta(days=DIAS_HISTORICO - 1), hoje)
    pres = presets(hoje)

    anterior = {}
    if os.path.exists(args.saida):
        try:
            anterior = json.load(open(args.saida, encoding="utf-8"))
        except ValueError:
            anterior = {}

    saida = {
        "versao": 2,
        "gerado_em": agora.isoformat(timespec="seconds"),
        "historico": faixa(hist),
        "presets": {k: faixa(v) for k, v in pres.items()},
    }
    env = os.environ
    saida["meta"] = (rodar("Meta Ads", coletar_meta, env["META_ACCESS_TOKEN"], hist, pres)
                     if env.get("META_ACCESS_TOKEN") else bloco_pendente("Falta META_ACCESS_TOKEN"))
    saida["hubspot"] = (rodar("HubSpot", coletar_hubspot, env["HUBSPOT_TOKEN"], hist)
                        if env.get("HUBSPOT_TOKEN") else bloco_pendente("Falta HUBSPOT_TOKEN"))

    faltando = [v for v in ("GADS_CLIENT_ID", "GADS_CLIENT_SECRET",
                            "GADS_REFRESH_TOKEN") if not env.get(v)]
    snapshot = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google_ads_snapshot.json")
    if not faltando:
        saida["google_ads"] = rodar("Google Ads", coletar_google_ads, hist)
    elif os.path.exists(snapshot):
        # cópia manual (Reportei) enquanto a API não está configurada; vale só para o período dela.
        # Este arquivo fica fora do Git (repositório público).
        saida["google_ads"] = json.load(open(snapshot, encoding="utf-8"))
    else:
        saida["google_ads"] = bloco_pendente("Falta configurar a Google Ads API (" + ", ".join(faltando) + ")")

    saida["ga4"] = (rodar("GA4", coletar_ga4, hist) if env.get("GA4_SERVICE_ACCOUNT_JSON")
                    else bloco_pendente("Falta GA4_SERVICE_ACCOUNT_JSON"))
    saida["linkedin"] = bloco_pendente(
        "Integração ainda não feita: a conta 511038871 está sem campanhas com números e o app "
        "da Marketing API precisa de aprovação do LinkedIn (ver INTEGRACOES.md)")

    # canal que falhou agora mas tinha dado bom antes: mantém o anterior, marcado como desatualizado
    for canal in ("meta", "hubspot", "google_ads", "ga4"):
        if saida[canal].get("status") == "erro" and anterior.get("versao") == 2 \
                and anterior.get(canal, {}).get("status") == "ok":
            velho = anterior[canal]
            velho["desatualizado"] = True
            velho["erro_atual"] = saida[canal]["motivo"]
            saida[canal] = velho
        elif saida[canal].get("status") == "ok":
            saida[canal]["coletado_em"] = saida["gerado_em"]

    tmp = args.saida + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.saida)
    print(f"✓ {args.saida} ({os.path.getsize(args.saida) / 1024:.0f} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
