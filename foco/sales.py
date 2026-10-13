"""Vendas: totais por evento, fotos vendidas e média dos fotógrafos."""
import re
from collections import Counter
from datetime import date

from bs4 import BeautifulSoup


def _money(s):
    s = (s or "").replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _int(s):
    try:
        return int((s or "0").replace(".", "").strip())
    except ValueError:
        return 0


def parse_sales_table(html):
    """/accounting/orders-by-competition-by-user → {id: {...}}"""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.select("table tbody tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) < 5:
            continue
        m = re.match(r"(\d+)\s*-\s*(.+)", tds[0])
        if not m:
            continue
        out[m.group(1)] = {
            "id": m.group(1),
            "name": m.group(2).strip(),
            "date": tds[1],
            "revenue": _money(tds[2]),
            "photos": _int(tds[4]),
        }
    return out


def fetch_sales(client, year=None):
    year = year or date.today().year
    html = client.get("/accounting/orders-by-competition-by-user", {"OrdersByCompetitionSearch[year]": year})
    data = parse_sales_table(html)
    if not data:  # se o parâmetro de ano não existir, usa o padrão da página
        data = parse_sales_table(client.get("/accounting/orders-by-competition-by-user"))
    return data


def parse_sold_images(html):
    soup = BeautifulSoup(html, "html.parser")
    pane = soup.select_one('[id$="-tab0"]') or soup
    rows, order = [], ""
    for tr in pane.select("table tbody tr"):
        img = tr.find("img")
        if not img:
            continue
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if tds and tds[0]:
            order = tds[0]
        code = tds[2] if len(tds) > 2 else img.get("src", "").rsplit("/", 1)[-1].split(".")[0]
        rows.append({
            "order": order,
            "res": tds[1] if len(tds) > 1 else "",
            "code": code,
            "hour": tds[4] if len(tds) > 4 else "",
            "img": img.get("src"),
        })
    return rows


def fetch_sold_images(client, comp_id, max_pages=40):
    all_rows, prev_first = [], None
    for page in range(1, max_pages + 1):
        html = client.get("/report/sold-images", {
            "SoldImages[competition_id]": comp_id, "page-photo": page, "per-page": 50,
        })
        rows = parse_sold_images(html)
        if not rows or rows[0]["img"] == prev_first:
            break
        prev_first = rows[0]["img"]
        seen = {r["img"] + r["order"] for r in all_rows}
        new = [r for r in rows if r["img"] + r["order"] not in seen]
        if not new:  # página repetida = acabou
            break
        all_rows.extend(new)
    return all_rows


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
        if len(tds) >= 3 and tds[0] != "TOTAL":
            out[tds[0]] = {"qty": _int(tds[1]), "gross": _money(tds[2])}
    return out


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


def fetch_order_times(client, when):
    """{pedido: "dd/mm/aaaa hh:mm"} do relatório "Dados do pedido" (mês atual e anterior)."""
    out = {}
    months = [(when.month, when.year)]
    prev = (when.month - 1 or 12, when.year - (1 if when.month == 1 else 0))
    months.append(prev)
    for month, year in months:
        html = client.get("/report/orders", {"Report[month]": month, "Report[year]": year})
        for tr in BeautifulSoup(html, "html.parser").select("table tbody tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) >= 2 and tds[0].isdigit():
                out[tds[0]] = tds[1]
    return out


def fetch_order_total(client, order_id):
    """Valor pago no pedido. A página tem dados do cliente: lemos só o total."""
    html = client.get("/report/order-detail", {"id": order_id})
    txt = BeautifulSoup(html, "html.parser").get_text("|", strip=True)
    m = re.search(r"\|Total\|\s*R\$\s*([\d.,]+)", txt)
    return _money(m.group(1)) if m else None
