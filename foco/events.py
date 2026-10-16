"""Lista de eventos disponíveis: leitura, filtro e nota."""
import re
from datetime import date, datetime, timedelta

from bs4 import BeautifulSoup

from . import config

STATES = {"SC": 24, "PR": 16, "RS": 21}

# Status a partir dos textos que aparecem no card (ordem importa)
STATUS_RULES = [
    ("nivel", "Nível insuficiente"),
    ("espera_encerrada", "Lista de espera encerrada"),
    ("encerrado", "Cadastro encerrado"),
    ("esgotado", "Vagas Esgotadas"),
    ("espera", "Lista de espera encerra em"),
    ("espera", "Entrar na Lista de Espera"),
    ("espera", "Lista de Espera"),
]
STATUS_LABEL = {
    "aberto": "🟢 Cadastro aberto",
    "espera": "🟡 Lista de espera aberta",
    "esgotado": "🔴 Vagas esgotadas",
    "encerrado": "⚫ Cadastro encerrado",
    "espera_encerrada": "⚫ Lista de espera encerrada",
    "nivel": "⚪ Nível insuficiente",
    "inscrito": "✅ Você já está inscrito",
}
OPEN_STATUSES = {"aberto", "espera"}


def _num(s):
    """Primeiro número do texto: 'R$ 1.234,50' → 1234.5 · '90% Fotógrafo' → 90"""
    if s is None:
        return None
    m = re.search(r"\d[\d.]*(?:,\d+)?", s)
    if not m:
        return None
    return float(m.group(0).replace(".", "").replace(",", "."))


def _grab(text, label, cast=_num):
    m = re.search(re.escape(label) + r"\s*\|\s*([^|]+)", text)
    return cast(m.group(1)) if m else None


def _event_id(w, modal):
    """Número do evento. Na "Minha Agenda" o card vem sem o modal, então há outras fontes."""
    if modal:
        return modal["id"].rsplit("-", 1)[-1]
    for attr in ("data-competition-id", "data-competition_id"):
        el = w.select_one(f"[{attr}]")
        if el and el[attr].isdigit():
            return el[attr]
    for el, attr, rx in ((w.select_one('[data-target^="#view-event-modal-"]'), "data-target", r"(\d+)$"),
                         (w.select_one('a[id^="link-event-"]'), "id", r"(\d+)$"),
                         (w.select_one('a[href*="/competition/information/"]'), "href", r"/information/(\d+)")):
        if el:
            m = re.search(rx, el.get(attr, ""))
            if m:
                return m.group(1)
    return None


def parse_future(html):
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for w in soup.select(".card-event-widget"):
        card = w.select_one(".event-card-fc")
        if not card:
            continue
        modal = w.select_one('.modal[id^="view-event-modal-"]')
        ev_id = _event_id(w, modal)
        if not ev_id:
            continue

        title = card.select_one(".event-title-fc").get_text(" ", strip=True)
        texts = card.select(".icon-text-card .event-text-fc")
        sport = texts[0].get_text(" ", strip=True) if texts else ""
        city_el = card.select_one(".icon-text-card-location-fc .event-city-fc")
        uf_el = card.select_one(".event-state-fc")
        city = city_el.get_text(strip=True) if city_el else ""
        uf = uf_el.get_text(strip=True).replace("/", "").strip() if uf_el else ""

        mt = modal.get_text("|", strip=True) if modal else ""
        # os modais ficam dentro do card: tira eles antes de ler status/data
        card = BeautifulSoup(str(card), "html.parser")
        for m in card.select(".modal"):
            m.decompose()
        card_text = card.get_text(" | ", strip=True)
        dm = re.search(r"(\d{2})/(\d{2})/(\d{2})\b", card_text)
        ev_date = date(2000 + int(dm.group(3)), int(dm.group(2)), int(dm.group(1))).isoformat() if dm else None

        status = "aberto"
        for key, needle in STATUS_RULES:
            if needle in card_text:
                status = key
                break

        timer = card.select_one("p.timer[data-countdown]")
        warn = card.select_one(".register-date-warning")
        deadline_label = warn.get_text(" ", strip=True).split(":")[0] if warn else None
        vagas = re.search(r"Vagas restantes:\s*\|?\s*(\d+)", card_text)
        link = card.select_one("a.link-event")
        partnership = None
        if card.select_one(".event-badge-fc--official"):
            partnership = "oficial"
        elif card.select_one(".event-badge-fc--no_partnership"):
            partnership = "sem"

        if re.search(r"Descadastrar|Cancelar cadastro|Você está cadastrado|Cadastrado", mt):
            status = "inscrito"
        ev = {
            "id": ev_id,
            "title": title,
            "sport": sport,
            "city": city,
            "uf": uf,
            "date": ev_date,
            "status": status,
            "deadline": timer["data-countdown"] if timer else None,
            "deadline_label": deadline_label,
            "vagas": int(vagas.group(1)) if vagas else None,
            "partnership": partnership,
            "link": link["href"] if link and link.get("href") else None,
            "commission": _grab(mt, "Oficial:"),
            "points": _grab(mt, "Pontos:"),
            "photographers": _grab(mt, "Fotógrafos:"),
            "waitlist": _grab(mt, "Fotógrafos na lista de espera:"),
            "price_premium": _grab(mt, "Premium:"),
            "price_high": _grab(mt, "Alta:"),
            "price_video": _grab(mt, "Vídeo:"),
            "price_medium": _grab(mt, "Média:"),
            "price_low": _grab(mt, "Baixa:"),
            "credits": _grab(mt, "Créditos:"),
            "identification": _grab(mt, "Identificação dos Atletas:", lambda v: v.strip()),
            "organizer": _grab(mt, "Organizador:", lambda v: v.strip()),
            "launch": _grab(mt, "Lançamento:", lambda v: v.strip()),
        }
        events.append(ev)
    return events


def has_next_page(html, page):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.select(".pagination a"):
        if a.get_text(strip=True) == str(page + 1):
            return True
    return False


def fetch_all(client, days_ahead=None):
    days_ahead = days_ahead or config.DAYS_AHEAD
    today = date.today()
    out = {}
    for uf, sid in STATES.items():
        page = 1
        while page <= 40:
            html = client.get(
                "/competition/future",
                {
                    "CompetitionSearch[state_id]": sid,
                    "CompetitionSearch[future_list_date_from]": today.strftime("%d/%m/%Y"),
                    "CompetitionSearch[future_list_date_to]": (today + timedelta(days=days_ahead)).strftime("%d/%m/%Y"),
                    "page": page,
                },
            )
            for ev in parse_future(html):
                ev["uf"] = ev["uf"] or uf
                out[ev["id"]] = ev
            if not has_next_page(html, page):
                break
            page += 1
    if not out:
        raise RuntimeError("A lista de eventos veio vazia (o painel mudou?)")
    return list(out.values())


def fetch_waitlist(client, max_pages=6):
    """Pedidos pendentes: página "Na lista de espera" (ainda não estão na sua agenda)."""
    today = date.today().isoformat()
    out = {}
    for page in range(1, max_pages + 1):
        html = client.get("/competition/my-waiting-list", {"page": page})
        evs = parse_future(html)
        for ev in evs:
            ev["mine"] = "espera"
            out[ev["id"]] = ev
        # a lista vem da data mais distante para a mais antiga: para quando chegar no passado
        if not evs or all((e["date"] or "9999") < today for e in evs) or not has_next_page(html, page):
            break
    return {k: v for k, v in out.items() if (v["date"] or "9999") >= today}


def fetch_schedule(client):
    """Eventos confirmados: aba "Minha Agenda". A página traz quantos eventos há em cada dia;
    os cards de cada dia vêm de /competition/load-competitions-by-date."""
    today = date.today().isoformat()
    html = client.get("/competition/schedule")
    days = [d for d, n in re.findall(r'data-time-frame-index="([\d-]+)"\s+data-total-competitions="(\d+)"', html)
            if int(n) > 0 and d >= today]
    out = {}
    for d in days:
        part = client.get("/competition/load-competitions-by-date", {
            "date": d, "CompetitionSearch[name]": "", "CompetitionSearch[group_by]": "day",
            "day-group-date-picker": d,
        })
        for ev in parse_future(part):
            ev["mine"] = "inscrito"
            ev["date"] = ev["date"] or d
            out[ev["id"]] = ev
    return out


def fetch_agenda(client):
    """Agenda confirmada + pedidos na lista de espera (confirmado ganha)."""
    agenda = {k: v for k, v in fetch_waitlist(client).items()}
    agenda.update(fetch_schedule(client))
    return agenda


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
