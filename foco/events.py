"""Lista de eventos disponíveis: leitura, filtro e nota."""
import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from . import config

STATES = {"SC": 24, "PR": 16, "RS": 21}

STATUS_LABEL = {
    "aberto": "🟢 Cadastro aberto",
    "espera": "🟡 Lista de espera aberta",
    "esgotado": "🔴 Vagas esgotadas",
    "encerrado": "⚫ Cadastro encerrado",
    "espera_encerrada": "⚫ Lista de espera encerrada",
    "nivel": "⚪ Nível insuficiente",
    "inscrito": "✅ Você já está inscrito",
    "aprovacao": "⚪ Aguardando aprovação do organizador",
}
OPEN_STATUSES = {"aberto", "espera"}
PENDING_ORGANIZER = 11  # status do evento: aguardando aprovação do organizador
PUBLIC_PAGE = "https://www.focoradical.com.br/evento/"
DETAIL_TTL_H = 6        # detalhes (fotógrafos, preços) valem por algumas horas: não pede tudo toda hora
DETAIL_KEYS = ("commissions", "points", "credits", "photographersCount", "photographersCountIsWaitingApproval",
               "waitingListTotalPending", "priceProfile", "identificationType", "organizerContact", "formatedLaunchDate")
SCHEDULE_DAYS = 60      # a "Minha Agenda" só aceita ~2 meses por consulta


# ---------------------------------------------------------------- leitura (API do painel novo, nov/2026)
# O painel de eventos virou telas novas em 17/11/2026. Lista: /next-api/competition/future-list,
# detalhes de cada evento (fotógrafos, preços, comissão): /next-api/competition/future-detail?id=.

def _past(ts):
    """'2026-11-20 18:00:00' já passou? (horário de Brasília, comparado como texto)"""
    if not ts:
        return False
    from datetime import timezone
    now = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    return str(ts).replace("T", " ")[:19] < now


def status_of(it):
    """A mesma regra do botão do card no site."""
    if it.get("userSignedToCompetition"):
        return "inscrito"
    if it.get("status") == PENDING_ORGANIZER:
        return "aprovacao"
    slots = it.get("eventSlotsAvailability") or {}
    if it.get("waitingListEnabled"):
        if it.get("waitingListStatus") == "rejected" or _past(it.get("waitingListDeadline")):
            return "espera_encerrada"
        if slots and not slots.get("isEligible", True):
            return "nivel"
        return "espera"
    if it.get("registerDate") and _past(it["registerDate"]):
        return "encerrado"
    if it.get("isPool") and slots:
        if not slots.get("isEligible", True):
            return "nivel"
        if slots.get("availableSlots") == 0:
            return "esgotado"
    return "aberto"


def _price(detail, word):
    for t in ((detail.get("priceProfile") or {}).get("imageTypes") or []):
        if word in (t.get("name") or "").lower():
            return t.get("price")
    return None


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_item(it, detail=None):
    """Um evento da API (lista + detalhe opcional) no formato que o resto do bot usa."""
    d = detail or {}
    slots = it.get("eventSlotsAvailability") or {}
    badge = (it.get("partnershipBadge") or {}).get("variant")
    wl_open = it.get("waitingListEnabled")
    deadline = it.get("waitingListDeadline") if wl_open else it.get("registerDate")
    count = d.get("photographersCount")
    waiting = bool(d.get("photographersCountIsWaitingApproval"))
    org = d.get("organizerContact")
    if isinstance(org, dict):
        org = org.get("name") or org.get("company") or None
    profile = d.get("priceProfile") or {}
    return {
        "id": str(it["id"]),
        "title": (it.get("name") or "").strip(),
        "sport": ((it.get("sport") or {}).get("name") or "").strip(),
        "city": (it.get("place") or "").strip(),
        "uf": (it.get("state") or {}).get("abbreviation") or "",
        "date": (it.get("date") or "")[:10] or None,
        "status": status_of(it),
        "deadline": str(deadline)[:19] if deadline else None,
        "deadline_label": ("Lista de espera encerra em" if wl_open else "Limite de cadastro") if deadline else None,
        "vagas": slots.get("availableSlots"),
        "partnership": {"official": "oficial", "no_partnership": "sem", "photographer": "fotografo"}.get(badge),
        "link": PUBLIC_PAGE + it["path"] if it.get("path") else None,
        "commission": _float((d.get("commissions") or {}).get("officialRate")),
        "points": _float(d.get("points")),
        "photographers": None if waiting else _float(count),
        "waitlist": _float(count) if waiting else _float(d.get("waitingListTotalPending")),
        "price_premium": _price(d, "premium"),
        "price_high": _price(d, "alta"),
        "price_video": profile.get("videoPrice") if profile.get("isVideo") else None,
        "price_medium": _price(d, "média") or _price(d, "media"),
        "price_low": _price(d, "baixa"),
        "credits": _float(d.get("credits")),
        "identification": d.get("identificationType"),
        "organizer": org,
        "launch": d.get("formatedLaunchDate"),
    }


def _pages(client, path, params=None, max_pages=40):
    """Todas as páginas de uma lista da API ({items, _meta.pageCount})."""
    out, page = [], 1
    while page <= max_pages:
        j = client.get_json(path, dict(params or {}, **({"page": page} if page > 1 else {})))
        out += j.get("items") or []
        if page >= ((j.get("_meta") or {}).get("pageCount") or 1):
            break
        page += 1
    return out


def fetch_details(client, ids, cache=None):
    """Detalhe de cada evento, guardado em `cache` (memória do bot) por DETAIL_TTL_H horas."""
    cache = cache if cache is not None else {}
    now = datetime.now().timestamp()
    out = {}
    for i in ids:
        c = cache.get(i)
        if c and now - c.get("t", 0) < DETAIL_TTL_H * 3600:
            out[i] = c["d"]
            continue
        try:
            full = client.get_json("/next-api/competition/future-detail", {"id": i})
            d = {k: full.get(k) for k in DETAIL_KEYS}  # só o que o bot usa (a memória fica pequena)
            cache[i] = {"t": now, "d": d}
            out[i] = d
        except Exception as ex:  # um detalhe faltando não derruba a lista
            print("detalhe do evento indisponível:", i, ex)
            out[i] = (c or {}).get("d")
    for k in [k for k in cache if k not in ids]:  # esquece eventos que saíram da lista
        del cache[k]
    return out


def fetch_all(client, days_ahead=None, cache=None):
    days_ahead = days_ahead or config.DAYS_AHEAD
    today = date.today()
    items = {}
    for uf, sid in STATES.items():
        for it in _pages(client, "/next-api/competition/future-list", {
            "CompetitionSearch[state_id]": sid,
            "CompetitionSearch[future_list_date_from]": today.strftime("%d/%m/%Y"),
            "CompetitionSearch[future_list_date_to]": (today + timedelta(days=days_ahead)).strftime("%d/%m/%Y"),
        }):
            items[str(it["id"])] = it
    if not items:
        raise RuntimeError("A lista de eventos veio vazia (o painel mudou?)")
    details = fetch_details(client, list(items), cache)
    return [parse_item(it, details.get(i)) for i, it in items.items()]


def fetch_waitlist(client, max_pages=6):
    """Pedidos pendentes: tela "Na lista de espera" (ainda não estão na sua agenda)."""
    today = date.today().isoformat()
    out = {}
    for it in _pages(client, "/next-api/photographer-events/my-waiting-list", max_pages=max_pages):
        if it.get("waitingListStatus") != "pending" or it.get("userSignedToCompetition"):
            continue  # recusado, ou já aprovado (aparece na agenda)
        ev = parse_item(it)
        if (ev["date"] or "9999") >= today:
            ev["mine"] = "espera"
            out[ev["id"]] = ev
    return out


def fetch_schedule(client, days_ahead=None):
    """Eventos confirmados: "Minha Agenda", pedida em blocos de ~2 meses."""
    days_ahead = days_ahead or config.DAYS_AHEAD
    start, end = date.today(), date.today() + timedelta(days=days_ahead)
    out = {}
    while start <= end:
        stop = min(start + timedelta(days=SCHEDULE_DAYS - 1), end)
        j = client.get_json("/next-api/photographer-events/schedule",
                            {"from": start.isoformat(), "to": stop.isoformat()})
        if j.get("errors"):
            raise RuntimeError(f"Minha Agenda recusou a consulta: {j['errors']}")
        for it in j.get("items") or []:
            ev = parse_item(it)
            ev["mine"] = "inscrito"
            out[ev["id"]] = ev
        start = stop + timedelta(days=1)
    return out


def fetch_agenda(client):
    """Agenda confirmada + pedidos na lista de espera (confirmado ganha)."""
    agenda = {k: v for k, v in fetch_waitlist(client).items()}
    agenda.update(fetch_schedule(client))
    return agenda


RANK_JSON_RX = re.compile(r'\\?"ranking\\?"\s*:\s*\{\s*\\?"rank\\?"\s*:\s*(\d+)\s*,\s*\\?"total\\?"\s*:\s*(\d+)')
RANK_RX = re.compile(r"classifica[çc][ãa]o no evento.*?(\d+)\s*[º°ª]?\s*de\s*(\d+)\s*fot", re.I | re.S)


def parse_ranking(html):
    """Painel do Evento: '"ranking":{"rank":9,"total":16}' nos dados da página (site novo)
    ou 'Sua classificação no evento ...: 27° de 63 fotógrafos' no texto (site antigo) → (rank, total)."""
    m = RANK_JSON_RX.search(html)
    if m:
        return int(m.group(1)), int(m.group(2))
    txt = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = RANK_RX.search(txt)
    return (int(m.group(1)), int(m.group(2))) if m else None


def fetch_ranking(client, comp_id):
    """Sua classificação no evento, lida no Painel do Evento. Só aparece nos eventos em que você está inscrito."""
    return parse_ranking(client.get(f"/competition/information/{comp_id}"))


# ---------------------------------------------------------------- nota

def sport_weight(sport, title):
    s = (sport + " " + title).lower()
    for words, w in config.SPORT_WEIGHTS:
        if any(x in s for x in words):
            return w
    return config.SPORT_DEFAULT


def size_of(ev):
    return max(ev.get("photographers") or 0, ev.get("waitlist") or 0)


def score(ev):
    """Nota de 0 a 10 + motivos. Pesos em config.py, calibrados com o seu histórico de vendas."""
    reasons = []
    pts = sport_weight(ev["sport"], ev["title"])
    reasons.append(f"{ev['sport'] or 'evento'}")

    size = size_of(ev)
    if size >= 20:
        pts += 3; reasons.append(f"evento grande ({int(size)} fotógrafos)")
    elif size >= 8:
        pts += 2; reasons.append(f"{int(size)} fotógrafos")
    elif size >= 3:
        pts += 1

    if ev.get("partnership") == "oficial":
        pts += 1; reasons.append("Parceria Foco")

    km = ev.get("km")
    if km is not None:
        if km <= 50:
            pts += 2; reasons.append("perto de casa")
        elif km <= 150:
            pts += 1
        elif km > config.MAX_KM:
            pts -= 2

    if ev.get("date"):
        wd = datetime.fromisoformat(ev["date"]).weekday()
        if wd >= 5:
            pts += 0.5; reasons.append("fim de semana")

    if ev.get("price_premium"):
        pts += 0.5; reasons.append("vende Premium")

    return max(0.0, min(10.0, round(pts, 1))), reasons


def is_relevant(ev):
    """SC até MAX_KM; PR/RS só eventos grandes; acima de MAX_KM só se for muito grande."""
    size = size_of(ev)
    km = ev.get("km")
    big = size >= config.BIG_EVENT_PHOTOGRAPHERS or (ev.get("partnership") == "oficial" and size >= 5)
    huge = size >= config.HUGE_EVENT_PHOTOGRAPHERS
    if km is not None and km > config.MAX_KM and not huge:
        return False
    if ev["uf"] != "SC" and not big:
        return False
    if any(w in ev["title"].lower() for w in config.IGNORE_TITLE_WORDS):
        return False
    return True
