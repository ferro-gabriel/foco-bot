"""Bot da Foco Radical do Gabriel.

Uso:
  python main.py listen     # o que o GitHub roda: responde comandos na hora e checa vendas a cada 3 min
  python main.py auto       # uma rodada só: comandos pendentes, vendas e tarefas do horário
  python main.py events     # checa eventos disponíveis agora
  python main.py sales      # checa vendas novas agora
  python main.py report     # relatório diário agora
  python main.py weekly     # relatório semanal agora
  python main.py test       # testa login e mostra um resumo, sem mandar nada
"""
import html
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from foco import config, events as ev_mod, geo, sales as sales_mod, state as st
from foco.client import FocoClient
from foco.telegram import Telegram

TZ = ZoneInfo("America/Sao_Paulo")
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# Eventos que você está trabalhando agora: ganham relatório detalhado todo dia
FOCUS_EVENTS = {"269944": "Vila Germânica – Oktoberfest 2026"}
# Palavras que SEMPRE geram alerta, mesmo fora dos filtros
WATCH_WORDS = ["oktoberfest", "vila germânica", "vila germanica", "sommerfest", "marejada", "fenarreco", "schützenfest", "fenachopp"]


def now():
    return datetime.now(TZ)


def brl(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def e(s):
    return html.escape(str(s or ""))


# ============================================================ EVENTOS

def fmt_event(ev):
    d = datetime.fromisoformat(ev["date"]) if ev.get("date") else None
    dist = ""
    if ev.get("km") is not None:
        h, m = divmod(ev.get("min") or 0, 60)
        dist = f" · 🚗 {ev['km']} km ({h}h{m:02d})"
    extra = []
    if ev.get("photographers"):
        extra.append(f"👥 {int(ev['photographers'])} fotógrafos")
    if ev.get("waitlist"):
        extra.append(f"⏳ {int(ev['waitlist'])} na lista de espera")
    if ev.get("vagas") is not None:
        extra.append(f"🎟 {ev['vagas']} vagas")
    if ev.get("partnership") == "oficial":
        extra.append("🤝 Parceria Foco")
    if ev.get("commission"):
        extra.append(f"💵 {int(ev['commission'])}%")
    prices = [f"{lbl} {brl(ev[k])}" for k, lbl in (("price_premium", "Premium"), ("price_high", "Alta"),
              ("price_medium", "Média"), ("price_low", "Baixa"), ("price_video", "Vídeo")) if ev.get(k)]
    info = []
    if ev.get("credits"):
        info.append(f"🪙 {int(ev['credits'])} créditos")
    if ev.get("points"):
        info.append(f"🏅 {int(ev['points'])} pontos")
    if ev.get("organizer"):
        info.append(f"🏢 {e(ev['organizer'])}")
    if ev.get("launch"):
        info.append(f"🚀 lançamento {e(ev['launch'])}")
    deadline = ""
    if ev.get("deadline"):
        try:
            dl = datetime.strptime(ev["deadline"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
            hrs = (dl - now()).total_seconds() / 3600
            if 0 < hrs < 72:
                deadline = f" · ⏰ fecha em {int(hrs)}h"
        except ValueError:
            pass
    panel = "https://www.focomarket.com.br/competition/future?CompetitionSearch%5Bname%5D=" + quote(ev["title"][:40])
    lines = [
        f"<b>{e(ev['title'])}</b>",
        f"📍 {e(ev['city'])}/{e(ev['uf'])}{dist} · 📅 {WEEKDAYS[d.weekday()] + ' ' + d.strftime('%d/%m') if d else '?'}",
        f"🏷 {e(ev['sport'])}" + (" · " + " · ".join(extra) if extra else ""),
        f"⭐ <b>{ev['score']}</b>/10 · {ev_mod.STATUS_LABEL.get(ev['status'], ev['status'])}{deadline}",
        *(["💲 " + " · ".join(prices)] if prices else []),
        *([" · ".join(info)] if info else []),
        f"<a href=\"{panel}\">Abrir no painel</a>" + (f" · <a href=\"{e(ev['link'])}\">página do evento</a>" if ev.get("link") else ""),
    ]
    if ev.get("mine") == "inscrito":
        lines.insert(1, "✅ <b>Você já está inscrito</b>")
    elif ev.get("mine") == "espera":
        lines.insert(1, "⏳ <b>Você já pediu (lista de espera, aguardando aprovação)</b>")
    if ev.get("conflicts"):
        lines.insert(1, "⚠️ Nesse dia você já tem: " + "; ".join(e(c) for c in ev["conflicts"]))
    return "\n".join(lines)


def mark_agenda(events, agenda):
    """Marca o que já é seu e avisa conflito de data com eventos em que você está inscrito."""
    by_date = {}
    for a in agenda.values():
        if a.get("date") and a.get("mine") == "inscrito":
            by_date.setdefault(a["date"], []).append(a)
    for ev in events:
        mine = agenda.get(ev["id"])
        ev["mine"] = mine["mine"] if mine else None
        same_day = [a for a in by_date.get(ev.get("date"), []) if a["id"] != ev["id"]]
        ev["conflicts"] = [a["title"].title()[:45] for a in same_day]
    return events


def get_agenda(client, state):
    agenda = ev_mod.fetch_agenda(client)
    cache = state.setdefault("geo", {})
    for a in agenda.values():
        if a.get("city"):
            a.update(geo.distance(a["city"], a["uf"], cache))
    return agenda


def fmt_agenda(agenda):
    def line(a):
        d = datetime.fromisoformat(a["date"])
        dist = f" · 🚗 {a['km']} km" if a.get("km") is not None else ""
        return (f"<b>{WEEKDAYS[d.weekday()]} {d.strftime('%d/%m/%y')}</b> · {e(a['title'].title())}\n"
                f"      📍 {e(a['city'])}/{e(a['uf'])}{dist}")

    confirmed = sorted([a for a in agenda.values() if a["mine"] == "inscrito"], key=lambda x: x["date"])
    pending = sorted([a for a in agenda.values() if a["mine"] == "espera"], key=lambda x: x["date"])
    lines = ["🗓 <b>Sua agenda (Minha Agenda)</b>"]
    if confirmed:
        per_day = {}
        for a in confirmed:
            per_day.setdefault(a["date"], []).append(a)
        for a in confirmed:
            warn = " ⚠️ <i>2+ eventos no dia</i>" if len(per_day[a["date"]]) > 1 else ""
            lines.append("✅ " + line(a) + warn)
    else:
        lines.append("Nenhum evento confirmado daqui pra frente.")
    if pending:
        lines.append("\n⏳ <b>Aguardando aprovação (lista de espera)</b>")
        lines += ["⏳ " + line(a) for a in pending]
    return "\n".join(lines)


def check_agenda_changes(agenda, tg, state):
    old = state.get("agenda")
    state["agenda"] = {k: {"mine": v["mine"], "title": v["title"], "date": v["date"]} for k, v in agenda.items()}
    if old is None:
        return
    for k, v in agenda.items():
        before = (old.get(k) or {}).get("mine")
        if v["mine"] == "inscrito" and before == "espera":
            d = datetime.fromisoformat(v["date"])
            tg.send(f"🎉 <b>Você foi aprovado! Entrou na sua agenda:</b>\n{e(v['title'])}\n📅 {WEEKDAYS[d.weekday()]} {d.strftime('%d/%m')} · 📍 {e(v['city'])}/{e(v['uf'])}")
    for k, v in old.items():
        if k not in agenda and v.get("mine") == "espera" and (v.get("date") or "") >= date.today().isoformat():
            tg.send(f"ℹ️ <b>{e(v['title'])}</b> ({v['date'][8:10]}/{v['date'][5:7]}) saiu da sua lista de espera "
                    "e não entrou na agenda. Pode ter sido recusado ou a lista foi fechada.")


def enrich(events, state):
    cache = state.setdefault("geo", {})
    for ev in events:
        if ev.get("city"):
            ev.update(geo.distance(ev["city"], ev["uf"], cache))
        else:
            ev.update({"km": None, "min": None})
        ev["score"], ev["reasons"] = ev_mod.score(ev)
        text = (ev["title"] + " " + ev["city"]).lower()
        ev["watch"] = any(w in text for w in WATCH_WORDS)
        ev["relevant"] = ev["watch"] or ev_mod.is_relevant(ev)
    return events


def job_events(client, tg, state, morning=False):
    events = enrich(ev_mod.fetch_all(client), state)
    try:
        agenda = get_agenda(client, state)
        check_agenda_changes(agenda, tg, state)
    except Exception as ex:
        print("agenda indisponível:", ex)
        agenda = {}
    mark_agenda(events, agenda)
    seen = state.setdefault("events", {})
    first_run = not seen
    relevant = [x for x in events if x["relevant"] and not x["mine"]]

    new, changed, deadlines = [], [], []
    for ev in relevant:
        old = seen.get(ev["id"])
        if old is None:
            if not first_run:
                new.append(ev)
        else:
            if ev["status"] != old["status"] and ev["status"] in ev_mod.OPEN_STATUSES:
                changed.append((ev, old["status"]))
        if (ev["score"] >= config.GOOD_SCORE or ev["watch"]) and ev["status"] in ev_mod.OPEN_STATUSES and ev.get("deadline"):
            try:
                dl = datetime.strptime(ev["deadline"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
                hrs = (dl - now()).total_seconds() / 3600
            except ValueError:
                hrs = None
            if hrs is not None and 0 < hrs < config.DEADLINE_ALERT_HOURS and (old or {}).get("deadline_alerted") != ev["deadline"]:
                deadlines.append(ev)

    for ev in events:
        prev = seen.get(ev["id"], {})
        seen[ev["id"]] = {
            "status": ev["status"], "score": ev["score"], "title": ev["title"], "date": ev["date"],
            "deadline_alerted": ev["deadline"] if ev in deadlines else prev.get("deadline_alerted"),
        }
    # limpa eventos que já passaram
    cutoff = (date.today() - timedelta(days=3)).isoformat()
    for k in [k for k, v in seen.items() if (v.get("date") or "9999") < cutoff]:
        del seen[k]

    by_score = lambda xs: sorted(xs, key=lambda x: (-x["score"], x.get("date") or ""))

    if first_run:
        top = by_score([x for x in relevant if x["status"] in ev_mod.OPEN_STATUSES])[:10]
        msg = [f"🚀 <b>Bot ligado!</b> Encontrei {len(events)} eventos em SC/PR/RS nos próximos {config.DAYS_AHEAD // 30} meses; "
               f"{len(relevant)} passam nos seus filtros.\n\n<b>Melhores com cadastro aberto agora:</b>"]
        msg += [fmt_event(x) for x in top] or ["Nenhum aberto no momento."]
        tg.send("\n\n".join(msg))
        return

    for ev in deadlines:
        tg.send("⏰ <b>Cadastro fechando!</b>\n\n" + fmt_event(ev))
    if len(new) > 15:  # ex.: quando a busca passa a olhar mais longe
        top = by_score([x for x in new if x["status"] in ev_mod.OPEN_STATUSES])[:10]
        tg.send(f"🆕 <b>{len(new)} eventos novos</b> (inclusive meses à frente). "
                f"Os 10 melhores com cadastro ou lista de espera aberta:\n\n" + "\n\n".join(fmt_event(x) for x in top))
    elif new:
        tg.send(f"🆕 <b>{len(new)} evento(s) novo(s)</b>\n\n" + "\n\n".join(fmt_event(x) for x in by_score(new)))
    for ev, old_status in changed:
        what = "abriu vaga" if ev["status"] == "aberto" else "abriu lista de espera"
        tg.send(f"🔔 <b>Mudou: {what}</b> (antes: {ev_mod.STATUS_LABEL.get(old_status, old_status)})\n\n" + fmt_event(ev))

    if morning:
        top = by_score([x for x in relevant if x["status"] in ev_mod.OPEN_STATUSES and x["score"] >= config.GOOD_SCORE])[:8]
        if top:
            tg.send("☀️ <b>Bom dia! Melhores eventos abertos pra você:</b>\n\n" + "\n\n".join(fmt_event(x) for x in top))


# ============================================================ VENDAS

def when_text(dt):
    """datetime/ISO → 'hoje às 09:00' / 'ontem às 22:15' / '11/10 às 08:00'"""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    if dt is None:
        return None
    days = (now().date() - dt.date()).days
    day = "hoje" if days == 0 else ("ontem" if days == 1 else dt.strftime("%d/%m"))
    return f"{day} às {dt.strftime('%H:%M')}"


def media_items(client, rows):
    """Baixa os arquivos vendidos (sem marca d'água); se não der, usa a miniatura pública."""
    out = []
    for r in rows:
        data = client.download(r["view"]) if r.get("view") else None
        out.append({"data": data, "url": r.get("img"), "video": r.get("video")})
    return out


def day_stats(items, day):
    xs = [i for i in items if (i.get("paid_at") or "")[:10] == day]
    return sum(i["commission"] for i in xs), len(xs), len({i["order"] for i in xs})


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def notify_order(client, tg, order, its, s, cid, avg_cache, day=None):
    """Um aviso por pedido: fotos sem marca d'água + tudo que dá pra saber da venda."""
    found = {}
    if cid:
        try:
            found = sales_mod.find_sold(client, cid, [i["code"] for i in its])
        except Exception as ex:
            print("fotos do pedido indisponíveis:", type(ex).__name__)
    rows = [found.get(i["code"]) or {"code": i["code"], "res": i["res"]} for i in its]
    kinds = Counter((i["res"] or "Foto").split()[0] for i in its)
    mix = ", ".join(f"{n} {k}" for k, n in kinds.most_common())
    mine = sum(i["commission"] for i in its)
    try:
        total = sales_mod.fetch_order_total(client, order)
    except Exception:
        total = None
    hours = sorted({r["hour"][:5] for r in rows if r.get("hour")})

    cap = [f"💰 <b>Venda nova!</b> {e(s['name']) if s else 'evento ' + e(cid or '?')}",
           f"🛒 Pedido {e(order)} · {plural(len(its), 'foto', 'fotos')} ({e(mix)})"]
    sold_at = when_text(its[0].get("paid_at"))
    if sold_at:
        cap.append(f"⏰ Pago {sold_at}" + (f" · {e(its[0]['payment'])}" if its[0].get("payment") else ""))
    cap.append(f"💵 Sua parte: <b>+{brl(mine)}</b>" + (f" · cliente pagou {brl(total)}" if total else ""))
    if hours:
        cap.append(("📷 Tirada às " if len(hours) == 1 else "📷 Tiradas às ") + ", ".join(hours[:10]))
    if s:
        cap.append(f"📈 No evento: <b>{brl(s['revenue'])}</b> · {s['photos']} fotos"
                   + (f" · {s['videos']} vídeos" if s.get("videos") else "")
                   + (f" · {s['orders']} pedidos" if s.get("orders") else ""))
        if cid not in avg_cache:
            try:
                avg_cache[cid] = sales_mod.fetch_average(client, cid)[0]
            except Exception:
                avg_cache[cid] = None
        avg = avg_cache[cid]
        if avg:
            cap.append(f"👥 Média dos fotógrafos: {brl(avg)} (você {s['revenue'] / avg:.1f}x)")
    if day:
        cap.append(f"📅 Hoje: <b>{brl(day[0])}</b> em {plural(day[1], 'foto', 'fotos')} ({plural(day[2], 'pedido', 'pedidos')})")
    caption = "\n".join(cap)

    media = media_items(client, [r for r in rows if r.get("view") or r.get("img")])
    if not media:
        tg.send(caption)
    for j in range(0, len(media), 10):  # Telegram aceita até 10 por álbum
        tg.album(media[j:j + 10], caption if j == 0 else f"Pedido {e(order)} (continuação)")


def recent_ids(sales, days=45):
    cutoff = date.today() - timedelta(days=days)
    out = []
    for cid, s in sales.items():
        try:
            d = datetime.strptime(s["date"], "%d/%m/%Y").date()
        except ValueError:
            continue
        if d >= cutoff:
            out.append(cid)
    return out


def job_sales(client, tg, state):
    """Checa "Pedidos confirmados" (uma foto por linha, da mais nova pra mais antiga) e avisa cada
    pedido novo uma vez só. Retorna quantos pedidos foram avisados."""
    for old in ("sold_codes", "sales_retry"):  # memória do painel antigo
        state.pop(old, None)
    seen = state.get("seen_sales")
    today = now().date().isoformat()
    items = sales_mod.fetch_confirmed(client, set(seen or []), today=today)

    if seen is None:  # primeira execução: só grava a base
        current = sales_mod.fetch_sales(client)
        state["sales"] = current
        state["seen_sales"] = [i["key"] for i in items]
        year = [v for v in current.values() if v["date"].endswith(str(now().year))]
        rev, n, orders = day_stats(items, today)
        tg.send(f"💰 Monitor de vendas ligado. Ano até agora: <b>{brl(sum(v['revenue'] for v in year))}</b> em "
                f"{sum(v['photos'] for v in year)} fotos.\nHoje: <b>{brl(rev)}</b> em {plural(n, 'foto', 'fotos')}.\n"
                "Vou te avisar a cada venda nova, com as fotos sem marca d'água.")
        return 0

    known = set(seen)
    fresh = [i for i in items if i["key"] not in known]
    if not fresh:
        return 0
    current = sales_mod.fetch_sales(client)
    state["sales"] = current
    orders = {}
    for i in fresh:
        orders.setdefault(i["order"], []).append(i)
    day = day_stats(items, today)
    avg_cache = {}
    ordered = sorted(orders, key=lambda o: (orders[o][0].get("paid_at") or "", o))
    for n, order in enumerate(ordered):
        its = orders[order]
        cid = sales_mod.comp_of(its[0]["code"], current)
        try:
            notify_order(client, tg, order, its, current.get(cid), cid, avg_cache,
                         day if n == len(ordered) - 1 else None)
        finally:  # avisado (ou falhou de vez): não repete
            state["seen_sales"] = ([i["key"] for i in its] + state["seen_sales"])[:5000]
    return len(orders)


# ============================================================ RELATÓRIOS

def bar(n, mx, width=12):
    return "▇" * max(1 if n else 0, round(n / mx * width)) if mx else ""


def sold_key(r):
    return f"{r.get('order', '')}|{r.get('code', '')}"


def focus_block(client, cid, label, since_codes):
    rows = sales_mod.fetch_sold_images(client, cid)
    avg_rev, avg_photos = sales_mod.fetch_average(client, cid)
    types = sales_mod.fetch_image_types(client, cid)
    fresh = [r for r in rows if sold_key(r) not in since_codes] if since_codes is not None else []
    ppo, _ = sales_mod.photos_per_order(rows)
    total_qty = sum(t["qty"] for t in types.values()) or len(rows)
    lines = [f"🎯 <b>{e(label)}</b>"]
    if fresh:
        lines.append(f"Desde o último relatório: <b>{len(fresh)} fotos</b>")
    lines.append(f"Total: {len(rows)} fotos · {ppo:.1f} fotos por pedido")
    if avg_rev:
        lines.append(f"Média dos fotógrafos no evento: {brl(avg_rev)} ({avg_photos:.0f} fotos)")
    if types:
        mix = " · ".join(f"{k.split()[0]} {round(v['qty'] / total_qty * 100)}%" for k, v in types.items())
        lines.append(f"Mix: {mix}")
    base = fresh if len(fresh) >= 5 else rows
    hist = sales_mod.hour_histogram(base)
    if hist:
        mx = max(hist.values())
        order = sorted(hist, key=lambda h: (h + 24 - 12) % 24)  # tarde → madrugada
        lines.append("\n<b>Horário em que as fotos vendidas foram tiradas</b>" + (" (novas)" if base is fresh else "") + ":")
        lines.append("<code>" + "\n".join(f"{h:02d}h {bar(hist[h], mx)} {hist[h]}" for h in order) + "</code>")
        best = sorted(hist, key=lambda h: -hist[h])[:2]
        lines.append(f"🔥 Melhores horários: {', '.join(f'{h:02d}h' for h in best)}")
    return "\n".join(lines), fresh, rows


def job_report(client, tg, state, save=True):
    current = sales_mod.fetch_sales(client)
    state["sales"] = current
    snap = state.get("report_snapshot", {})
    if not snap.get("events"):
        snap = {}
    today = now().date()
    title = f"Relatório de {today.strftime('%d/%m')}" if save else f"Relatório agora ({now().strftime('%H:%M')})"
    lines = [f"📊 <b>{title}</b>"]

    deltas = []
    for cid, s in current.items():
        old = snap.get("events", {}).get(cid, {"revenue": 0, "photos": 0})
        dr, dp = s["revenue"] - old["revenue"], s["photos"] - old["photos"]
        if dp > 0 or dr > 0.009:
            deltas.append((dr, dp, s))
    if snap:
        tot_r = sum(d[0] for d in deltas)
        tot_p = sum(d[1] for d in deltas)
        lines.append(f"Desde o último relatório: <b>{brl(tot_r)}</b> em {tot_p} fotos")
        for dr, dp, s in sorted(deltas, key=lambda x: -x[0])[:8]:
            lines.append(f"• {e(s['name'][:40])}: +{brl(dr)} ({dp} fotos)")

    month = today.strftime("/%m/%Y")
    m_rev = sum(s["revenue"] for s in current.values() if s["date"].endswith(month))
    y_rev = sum(s["revenue"] for s in current.values() if s["date"].endswith(str(today.year)))
    lines.append(f"\nEventos deste mês: {brl(m_rev)} · Ano: <b>{brl(y_rev)}</b>")
    tg.send("\n".join(lines))

    focus_codes = state.setdefault("focus_codes", {})
    for cid, label in FOCUS_EVENTS.items():
        if cid not in current:
            continue
        txt, fresh, rows = focus_block(client, cid, label, set(focus_codes[cid]) if cid in focus_codes else None)
        tg.send(txt)
        if fresh:
            tg.album(media_items(client, fresh[-10:]), f"📸 Fotos que venderam desde o último relatório ({len(fresh)})")
        if save:
            focus_codes[cid] = [sold_key(r) for r in rows]

    if not save:
        return
    state["report_snapshot"] = {"date": today.isoformat(),
                                "events": {k: {"revenue": v["revenue"], "photos": v["photos"]} for k, v in current.items()}}


def job_weekly(client, tg, state, save=True):
    current = sales_mod.fetch_sales(client)
    state["sales"] = current
    snap = state.get("weekly_snapshot", {}).get("events", {})
    rows = []
    for cid, s in current.items():
        o = snap.get(cid, {"revenue": 0, "photos": 0})
        if s["revenue"] - o["revenue"] > 0.009:
            rows.append((s["revenue"] - o["revenue"], s["photos"] - o["photos"], s))
    lines = ["🗓 <b>Resumo da semana</b>"]
    if snap:
        lines.append(f"Total: <b>{brl(sum(r[0] for r in rows))}</b> em {sum(r[1] for r in rows)} fotos")
        for dr, dp, s in sorted(rows, key=lambda x: -x[0])[:10]:
            lines.append(f"• {e(s['name'][:40])}: {brl(dr)} ({dp})")

    # Você x média nos eventos dos últimos 30 dias
    comp = []
    for cid in recent_ids(current, 30):
        avg, _ = sales_mod.fetch_average(client, cid)
        if avg:
            comp.append((current[cid]["revenue"] / avg, current[cid]))
    if comp:
        lines.append("\n<b>Você × média dos fotógrafos (últimos 30 dias)</b>")
        for ratio, s in sorted(comp, key=lambda x: -x[0]):
            icon = "🟢" if ratio >= 1.1 else ("🟡" if ratio >= 0.8 else "🔴")
            lines.append(f"{icon} {e(s['name'][:38])}: {ratio:.2f}x")
    tg.send("\n".join(lines))
    if not save:
        return
    state["weekly_snapshot"] = {"date": now().date().isoformat(),
                                "events": {k: {"revenue": v["revenue"], "photos": v["photos"]} for k, v in current.items()}}


# ============================================================ AGENDADOR

HELP = """🤖 <b>Comandos</b>
/relatorio – vendas desde o relatório das 9h + Vila
/vendas – checa vendas novas agora
/agenda – sua agenda confirmada + o que está aguardando aprovação
/eventos – melhores eventos abertos agora, comparados com sua agenda
/semana – resumo da semana
/ajuda – esta lista

Também entendo palavras soltas: "relatório", "agenda", "eventos", "vendas"."""


def job_events_now(client, tg, state):
    """/eventos: lista os melhores abertos agora, sem mexer nos alertas."""
    events = enrich(ev_mod.fetch_all(client), state)
    try:
        agenda = get_agenda(client, state)
    except Exception:
        agenda = {}
    mark_agenda(events, agenda)
    top = sorted([x for x in events if x["relevant"] and not x["mine"] and x["status"] in ev_mod.OPEN_STATUSES],
                 key=lambda x: (-x["score"], x.get("date") or ""))[:10]
    tg.send("🔎 <b>Melhores eventos abertos agora</b>\n\n" + ("\n\n".join(fmt_event(x) for x in top) or "Nenhum aberto."))


def handle_command(text, client, tg, state):
    t = text.lower().lstrip("/").split("@")[0].strip()
    word = t.split()[0] if t else ""
    tg.typing()
    if word in ("start", "ajuda", "help", "comandos", "menu"):
        tg.send(HELP)
    elif word.startswith("relat"):
        job_sales(client, tg, state)
        job_report(client, tg, state, save=False)
    elif word.startswith("venda"):
        if not job_sales(client, tg, state):
            today = now().date().isoformat()
            items = sales_mod.fetch_confirmed(client, today=today)
            rev, n, orders = day_stats(items, today)
            msg = (f"Nenhuma venda nova desde a última checagem.\n📅 Hoje: <b>{brl(rev)}</b> em "
                   f"{plural(n, 'foto', 'fotos')} ({plural(orders, 'pedido', 'pedidos')})")
            if items:
                last = items[0]
                cid = sales_mod.comp_of(last["code"], state.get("sales") or {})
                name = (state.get("sales") or {}).get(cid, {}).get("name", "")
                msg += f"\n🕐 Última venda: {when_text(last['paid_at'])}" + (f" · {e(name)}" if name else "")
            tg.send(msg)
    elif word.startswith("agenda"):
        tg.send(fmt_agenda(get_agenda(client, state)))
    elif word.startswith("evento"):
        tg.send("🔎 Buscando eventos em SC, PR e RS… leva uns segundos.")
        job_events_now(client, tg, state)
    elif word.startswith("semana"):
        job_weekly(client, tg, state, save=False)
    else:
        tg.send("Não entendi. " + HELP)


def process_commands(client, tg, state, timeout=0):
    for text in tg.updates(timeout=timeout):
        try:
            handle_command(text, client, tg, state)
        except Exception as ex:
            tg.send(f"⚠️ Deu erro nesse comando: <code>{e(str(ex))[:300]}</code>")


def job_listen(client, tg, state, minutes=50, sales_every=180):
    """Fica escutando o Telegram (resposta na hora) e checando vendas a cada 3 min."""
    import time
    end = time.time() + minutes * 60
    last_sales = 0
    while time.time() < end:
        if time.time() - last_sales >= sales_every:
            job_auto(client, tg, state, commands=False)
            last_sales = time.time()
            st.save(state)  # se a rodada for cancelada, o que já foi avisado não se perde
        process_commands(client, tg, state, timeout=25)


def job_auto(client, tg, state, commands=True):
    t = now()
    done = state.setdefault("done", {})
    today = t.date().isoformat()
    errors, error_types = [], []
    if commands:
        process_commands(client, tg, state)

    def run(key, fn, *a, **kw):
        if done.get(key):
            return
        try:
            fn(*a, **kw)
            done[key] = True
        except Exception as ex:  # um job com erro não derruba os outros
            errors.append(f"{key}: {ex}")
            error_types.append(f"{key.split('-')[0]}: {type(ex).__name__}")

    try:
        job_sales(client, tg, state)
    except Exception as ex:
        errors.append(f"vendas: {ex}")
        error_types.append(f"vendas: {type(ex).__name__}")

    due = [h for h in config.EVENT_CHECK_HOURS if t.hour >= h]
    if due:  # só a checagem mais recente (se o bot reiniciar às 15h, não roda 7h..15h em sequência)
        h = due[-1]
        morning = not done.get(f"morning-{today}")
        run(f"events-{today}-{h}", job_events, client, tg, state, morning=morning)
        if morning and done.get(f"events-{today}-{h}"):
            done[f"morning-{today}"] = True
    if t.hour >= config.REPORT_HOUR:
        run(f"report-{today}", job_report, client, tg, state)
        if t.weekday() == config.WEEKLY_REPORT_WEEKDAY:
            run(f"weekly-{today}", job_weekly, client, tg, state)

    # esquece marcações com mais de 3 dias
    old = (t.date() - timedelta(days=3)).isoformat()
    for k in [k for k in done if k.split("-", 1)[1][:10] < old]:
        del done[k]

    if errors:
        n = state.get("error_streak", 0) + 1
        state["error_streak"] = n
        if n in (3, 12):  # avisa se persistir, sem spam
            tg.send("⚠️ O bot está com erro nas últimas execuções:\n<code>" + e("\n".join(errors))[:1500] + "</code>")
        print("ERROS:", ", ".join(error_types), "(detalhes vão pro Telegram)")
    else:
        state["error_streak"] = 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "auto"
    state = st.load()
    client = FocoClient()
    tg = Telegram(state)
    try:
        if cmd == "test":
            client.login()
            s = sales_mod.fetch_sales(client)
            print(f"✅ Login OK. Vendas por evento lidas ({len(s)} eventos).")
            items = sales_mod.fetch_confirmed(client)
            print(f"✅ Pedidos confirmados: {len(items)} fotos na 1ª página")
            if items:
                cid = sales_mod.comp_of(items[0]["code"], s)
                found = sales_mod.find_sold(client, cid, [items[0]["code"]]) if cid else {}
                r = next(iter(found.values()), None)
                data = client.download(r["view"]) if r and r.get("view") else None
                print(f"✅ Foto vendida sem marca d'água: {len(data) // 1024} KB" if data else "⚠️ Não baixei a foto sem marca")
            evs = ev_mod.parse_future(client.get("/competition/future"))
            print(f"✅ Página de eventos OK: {len(evs)} eventos na primeira página")
            return
        {"auto": job_auto, "listen": job_listen, "events": lambda c, t, s: job_events(c, t, s, morning=True),
         "sales": job_sales, "report": job_report, "weekly": job_weekly}[cmd](client, tg, state)
    finally:
        if cmd != "test":
            st.save(state)


if __name__ == "__main__":
    main()
