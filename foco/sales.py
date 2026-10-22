"""Vendas: totais por evento, fotos vendidas, pedidos e média dos fotógrafos.

Desde out/2026 as telas de vendas do painel são novas e leem uma API JSON (/next-api/...).
Os relatórios antigos que ainda existem (média, tipo de imagem, detalhe do pedido) seguem em HTML.
"""
import re
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

TZ = ZoneInfo("America/Sao_Paulo")
PAYMENT = {"pix": "Pix", "credito": "cartão de crédito", "crédito": "cartão de crédito", "debito": "cartão de débito",
           "boleto": "boleto"}


class SiteChanged(RuntimeError):
    """O painel respondeu, mas sem os dados esperados: o layout provavelmente mudou."""


def _money(s):
    if isinstance(s, (int, float)):
        return float(s)
    s = (s or "").replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _int(s):
    if isinstance(s, (int, float)):
        return int(s)
    try:
        return int((s or "0").replace(".", "").strip())
    except ValueError:
        return 0


def _br_date(iso):
    """'2026-10-11' → '11/10/2026' (formato usado no resto do bot)."""
    try:
        return datetime.strptime((iso or "")[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso or ""


def _pages(j):
    p = j.get("pagination") or {}
    meta = j.get("_meta") or {}
    return int(p.get("pageCount") or meta.get("pageCount") or 1)


# ---------------------------------------------------------------- vendas por evento

def parse_sales_json(j):
    """/next-api/accounting/orders-by-competition-by-user → {id: {...}}"""
    out = {}
    for it in j.get("items") or []:
        cid = str(it["competitionId"])
        out[cid] = {
            "id": cid,
            "name": (it.get("competitionName") or "").strip(),
            "date": _br_date(it.get("date")),
            "revenue": round(_money(it.get("photographerIncome")) + _money(it.get("spotCreatorIncome")), 2),
            "photos": _int(it.get("photoCount")),
            "videos": _int(it.get("videoCount")),
            "orders": _int(it.get("orderCount")),
        }
    return out


def fetch_sales(client):
    out, page = {}, 1
    while page <= 20:
        j = client.get_json("/next-api/accounting/orders-by-competition-by-user", {"page": page})
        out.update(parse_sales_json(j))
        if page >= _pages(j):
            break
        page += 1
    if not out:
        raise SiteChanged("O relatório 'Vendas por evento' veio vazio (o painel mudou?)")
    return out


# ---------------------------------------------------------------- fotos/vídeos vendidos

def parse_sold_json(j):
    kind = j.get("type") or "photo"
    rows = []
    for it in j.get("items") or []:
        taken = it.get("takenAt") or ""
        rows.append({
            "order": str(it.get("orderId") or ""),
            "res": it.get("resolution") or "",
            "code": it.get("code") or "",
            "hour": taken[11:19],
            "img": it.get("thumbUrl"),        # miniatura com marca d'água (pública)
            "view": it.get("viewUrl"),        # arquivo vendido, sem marca d'água (precisa de login)
            "video": kind == "video",
        })
    return rows


def _sold_page(client, comp_id, kind, page):
    return client.get_json("/next-api/report/sold-images",
                           {"competition_id": comp_id, "type": kind, "page-photo": page})


def fetch_sold_images(client, comp_id, kinds=("photo", "video"), max_pages=80):
    """Todas as fotos (e vídeos) vendidas no evento, do pedido mais antigo pro mais novo.
    A API devolve 10 por página; a ordem dela já mudou, então ordenamos pelo número do pedido."""
    rows = []
    for kind in kinds:
        page = 1
        while page <= max_pages:
            j = _sold_page(client, comp_id, kind, page)
            rows += parse_sold_json(j)
            if page >= _pages(j):
                break
            page += 1
    return sorted(rows, key=lambda r: _int(r["order"]))


def _ends_first(last, max_pages):
    """1, last, 2, last-1, ...: as vendas novas ficam numa das pontas da lista
    (no fim até out/2026, na 1ª página depois disso)."""
    lo, hi, out = 1, last, []
    while lo <= hi and len(out) < max_pages:
        out.append(lo)
        if hi != lo and len(out) < max_pages:
            out.append(hi)
        lo, hi = lo + 1, hi - 1
    return out


def find_sold(client, comp_id, codes, max_pages=16):
    """Acha fotos vendidas pelo código, procurando pelas duas pontas da lista."""
    want, found = set(codes), {}
    for kind in ("photo", "video"):
        first = _sold_page(client, comp_id, kind, 1)
        for p in _ends_first(_pages(first), max_pages):
            if not want - set(found):
                break
            j = first if p == 1 else _sold_page(client, comp_id, kind, p)
            for r in parse_sold_json(j):
                if r["code"] in want:
                    found.setdefault(r["code"], r)
        if not want - set(found):
            break
    return found


# ---------------------------------------------------------------- pedidos confirmados

def payment_name(s):
    low = (s or "").lower()
    for k, v in PAYMENT.items():
        if k in low:
            return v
    return re.sub(r"(?i)^pagarme\s+", "", s or "").strip()


def to_local(stamp):
    """Datas da API de pedidos vêm em UTC."""
    try:
        dt = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return dt.astimezone(TZ)


def parse_confirmed(j):
    out = []
    for it in j.get("items") or []:
        paid = to_local(it.get("paymentDate") or it.get("orderDate"))
        out.append({
            "key": f"{it.get('orderId')}|{it.get('photoCode')}",
            "order": str(it.get("orderId") or ""),
            "code": it.get("photoCode") or "",
            "res": it.get("imageTypeName") or "",
            "commission": round(_money(it.get("photographerCommission")) + _money(it.get("creatorCommission")), 2),
            "paid_at": paid.isoformat() if paid else None,
            "payment": payment_name(it.get("paymentTypeName")),
        })
    return out


def fetch_confirmed(client, older_than=None, max_pages=10):
    """Fotos vendidas, da mais nova pra mais antiga (50 por página).
    Lê páginas até chegar em vendas pagas antes de `older_than` (ISO, horário de Brasília);
    sem `older_than`, lê só a 1ª página."""
    out = []
    for page in range(1, max_pages + 1):
        j = client.get_json("/next-api/accounting/confirmed-orders", {"page": page, "per-page": 50})
        items = parse_confirmed(j)
        out += items
        if not items or page >= _pages(j) or not older_than:
            break
        if min((i["paid_at"] or "") for i in items) < older_than:
            break
    return out


def comp_of(code, comp_ids):
    """'RRLL2699441151020262232' → '269944' (o código da foto começa com o número do evento)."""
    digits = re.sub(r"^[A-Za-z]+", "", code or "")
    for cid in sorted(comp_ids, key=len, reverse=True):
        if digits.startswith(cid):
            return cid
    return None


# ---------------------------------------------------------------- relatórios antigos (HTML)

def fetch_average(client, comp_id):
    """Receita média e fotos médias dos fotógrafos no evento."""
    html = client.get("/accounting/get-convertion-by-competition", {"competition_id": comp_id})
    txt = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    m = re.search(r"R\$\s*([\d.,]+)\s+([\d.,]+)", txt)
    if not m:
        return None, None
    return _money(m.group(1)), _money(m.group(2))


def fetch_image_types(client, comp_id):
    html = client.get("/accounting/get-image-type-by-competition", {"competition_id": comp_id})
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.select("tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) >= 2 and tds[0].upper() != "TOTAL":
            out[tds[0]] = {"qty": _int(tds[1]), "gross": _money(tds[2]) if len(tds) > 2 else None}
    return out


def fetch_order_total(client, order_id):
    """Valor pago no pedido. A página tem dados do cliente: lemos só o total."""
    html = client.get("/report/order-detail", {"id": order_id})
    txt = BeautifulSoup(html, "html.parser").get_text("|", strip=True)
    m = re.search(r"\|Total\|\s*R\$\s*([\d.,]+)", txt)
    return _money(m.group(1)) if m else None


# ---------------------------------------------------------------- contas

def hour_histogram(rows):
    c = Counter()
    for r in rows:
        h = (r.get("hour") or "")[:2]
        if h.isdigit():
            c[int(h)] += 1
    return c


def photos_per_order(rows):
    orders = Counter(r["order"] for r in rows if r.get("order"))
    return (len(rows) / len(orders)) if orders else 0.0, orders
