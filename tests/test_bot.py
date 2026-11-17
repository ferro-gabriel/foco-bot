"""Testes offline: python -m unittest discover tests"""
import os
import sys
import json
import unittest
from datetime import date, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DRY_RUN"] = "1"

from foco import events, sales  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")


def fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def sales_json(vila_rev=1500.0, vila_photos=204):
    return {"items": [
        {"competitionId": 255342, "competitionName": "OKTOBERFEST RUN 2026", "date": "2026-10-11",
         "photographerIncome": 1000.0, "spotCreatorIncome": 0, "photoCount": 127, "videoCount": 2, "orderCount": 120},
        {"competitionId": 269944, "competitionName": "VILA GERMÂNICA 41ª OKTOBERFEST BLUMENAU 2026", "date": "2026-10-07",
         "photographerIncome": vila_rev, "spotCreatorIncome": 0, "photoCount": vila_photos, "videoCount": 0, "orderCount": 150},
    ], "pagination": {"page": 1, "pageSize": 50, "pageCount": 1, "totalCount": 2}}


def sold_item(order, code, res="Premium 4500 Pixels", taken="2026-10-12 22:11:21"):
    return {"orderId": order, "resolution": res, "code": code, "thumbUrl": f"https://cdn/x/ident/{code}.jpg",
            "takenAt": taken, "viewUrl": f"/photo/open?path=x%2F{code}.jpg&bucket=orders", "downloadUrl": None}


SOLD_ITEMS = [
    sold_item(11055461, "RRLL2699441"),
    sold_item(11055461, "RRLL2699442", "Alta 3450 Pixels", "2026-10-12 20:05:00"),
    sold_item(11055904, "RRLL2699443", taken="2026-10-12 20:40:00"),
]


def confirmed(item, order, code, paid, res="Premium 4500 Pixels", comm=7.4):
    return {"photoCode": code, "orderId": order, "photographerCommission": comm, "creatorCommission": 0,
            "orderDate": paid, "paymentDate": paid, "paymentTypeName": "Pagarme Pix", "imageTypeName": res}


def future_events():
    """Os 3 eventos de exemplo, lidos como o bot lê a API nova."""
    import json
    j = json.loads(fx("future.json"))
    return [events.parse_item(it, j["details"].get(str(it["id"]))) for it in j["items"]]


class ParseTests(unittest.TestCase):
    def test_future(self):
        evs = {e["id"]: e for e in future_events()}
        self.assertEqual(len(evs), 3)
        a = evs["300001"]
        self.assertEqual((a["city"], a["uf"], a["sport"]), ("Forquilhinha", "SC", "Corrida de Rua"))
        self.assertEqual(a["status"], "aberto")
        self.assertEqual(a["vagas"], 4)
        self.assertEqual(a["photographers"], 12)
        self.assertEqual(a["commission"], 90)
        self.assertEqual(a["price_premium"], 19.90)
        self.assertEqual(a["partnership"], "oficial")
        self.assertEqual(a["date"], "2030-10-17")
        b = evs["275615"]
        self.assertEqual(b["status"], "espera_encerrada")  # texto do modal não confunde
        self.assertEqual(b["waitlist"], 18)
        c = evs["300003"]
        self.assertEqual((c["status"], c["uf"], c["partnership"]), ("espera", "PR", "sem"))

    def test_relevance(self):
        evs = {e["id"]: e for e in future_events()}
        evs["300001"]["km"] = 220
        evs["300003"]["km"] = 250
        self.assertTrue(events.is_relevant(evs["300001"]))
        self.assertTrue(events.is_relevant(evs["300003"]))   # PR grande
        evs["300003"]["waitlist"] = 2
        self.assertFalse(events.is_relevant(evs["300003"]))  # PR pequeno
        evs["300001"]["km"] = 600
        self.assertFalse(events.is_relevant(evs["300001"]))  # longe e não é gigante
        s, _ = events.score(evs["275615"] | {"km": 50})
        self.assertGreaterEqual(s, 5)

    def test_sales(self):
        s = sales.parse_sales_json(sales_json())
        self.assertEqual(set(s), {"255342", "269944"})
        self.assertAlmostEqual(s["269944"]["revenue"], 1500.00)
        self.assertEqual(s["269944"]["photos"], 204)
        self.assertEqual(s["269944"]["date"], "07/10/2026")
        self.assertEqual(sales.comp_of("RRLL2699441151020262232", s), "269944")

    def test_confirmed(self):
        items = sales.parse_confirmed({"items": [confirmed(None, 1, "RRLL1", "2026-10-16 14:41:08")]})
        self.assertEqual(items[0]["paid_at"][:16], "2026-10-16T11:41")  # UTC → Brasília
        self.assertEqual(items[0]["payment"], "Pix")

    def test_status_rules(self):
        """Mesma regra do botão do card no site novo."""
        base = {"id": 1, "name": "X", "date": "2030-01-01", "state": {"abbreviation": "SC"}}
        st = lambda **kw: events.parse_item(dict(base, **kw))["status"]
        self.assertEqual(st(), "aberto")
        self.assertEqual(st(userSignedToCompetition=True, waitingListEnabled=True), "inscrito")
        self.assertEqual(st(status=11), "aprovacao")
        self.assertEqual(st(registerDate="2020-01-01 10:00:00"), "encerrado")
        self.assertEqual(st(isPool=True, eventSlotsAvailability={"isEligible": True, "availableSlots": 0}), "esgotado")
        self.assertEqual(st(isPool=True, eventSlotsAvailability={"isEligible": False}), "nivel")
        self.assertEqual(st(waitingListEnabled=True, waitingListStatus="rejected"), "espera_encerrada")
        self.assertEqual(st(waitingListEnabled=True, waitingListDeadline="2099-01-01 10:00:00"), "espera")

    def test_agenda(self):
        c = FakeClient()
        c.agenda_on = True
        ag = events.fetch_agenda(c)
        self.assertEqual({k: v["mine"] for k, v in ag.items()}, {"300001": "inscrito", "300003": "espera"})
        # a agenda só aceita ~2 meses por consulta: nenhum pedido maior que isso
        self.assertTrue(all((date.fromisoformat(t) - date.fromisoformat(f)).days < events.SCHEDULE_DAYS
                            for f, t in c.schedule_ranges))
        self.assertGreaterEqual(c.schedule_ranges[-1][1], (date.today() + timedelta(days=364)).isoformat())

    def test_fetch_all_paginates_and_caches_details(self):
        c = FakeClient()
        cache = {}
        evs = events.fetch_all(c, cache=cache)
        self.assertEqual(len(evs), 3)  # o mesmo evento em vários estados não duplica
        n = c.detail_calls
        self.assertEqual(n, 3)
        events.fetch_all(c, cache=cache)
        self.assertEqual(c.detail_calls, n)  # detalhes guardados: não pede de novo
        self.assertNotIn("registrationTerms", cache["300001"]["d"])  # memória enxuta

    def test_ranking(self):
        self.assertEqual(events.parse_ranking(RANK_HTML), (27, 63))
        rsc = r'self.__next_f.push([1,"{\"photographers\":{\"count\":16},\"ranking\":{\"rank\":9,\"total\":16},\"points\":1000'
        self.assertEqual(events.parse_ranking(rsc), (9, 16))
        self.assertIsNone(events.parse_ranking("<div>Número de fotógrafos 63</div>"))

    def test_sold(self):
        rows = sales.parse_sold_json({"type": "photo", "items": SOLD_ITEMS})
        self.assertEqual([r["order"] for r in rows], ["11055461", "11055461", "11055904"])
        self.assertTrue(rows[0]["view"].startswith("/photo/open"))
        self.assertEqual(sales.hour_histogram(rows)[20], 2)
        ppo, _ = sales.photos_per_order(rows)
        self.assertAlmostEqual(ppo, 1.5)

    def test_find_sold_either_order(self):
        """A lista de fotos vendidas já veio do mais antigo pro mais novo e depois o contrário (out/2026)."""
        items = [sold_item(11000000 + i, f"RRLL269944{i:03d}") for i in range(590)]
        for newest_first in (False, True):
            xs = items[::-1] if newest_first else items

            class C:
                def get_json(self, path, params=None):
                    p = params["page-photo"]
                    return {"type": params["type"], "items": xs[(p - 1) * 10:p * 10] if params["type"] == "photo" else [],
                            "pagination": {"pageCount": 59}}
            found = sales.find_sold(C(), "269944", ["RRLL269944589"])
            self.assertIn("RRLL269944589", found, newest_first)
            rows = sales.fetch_sold_images(C(), "269944")
            self.assertEqual(rows[-1]["code"], "RRLL269944589")



RANK_HTML = """<div class="info-section mb-3 d-flex flex-column justify-content-between">
<span class="text-sm my-2"><strong>Sua classificação no evento</strong> (com base no seu ranking):</span>
<span class="event-info-value font-medium text-sm">
    27º de 63 fotógrafos                </span></div>"""

class FakeClient:
    """Simula o site: vendas crescem entre as chamadas."""
    def __init__(self):
        self.sales = sales_json()
        self.confirmed = [confirmed(None, 11050000, "RRLL2699440", "2026-10-12 10:00:00")]
        self.agenda_on = False
        self.downloads = 0
        self.expired = False
        self.logged = True
        self.detail_calls = 0
        self.schedule_ranges = []

    def get_json(self, path, params=None):
        if path == "/next-api/accounting/orders-by-competition-by-user":
            return self.sales
        if path == "/next-api/accounting/confirmed-orders":
            page, per = params.get("page", 1), 50
            self.pages_read = max(getattr(self, "pages_read", 0), page)
            return {"items": self.confirmed[(page - 1) * per:page * per],
                    "_meta": {"pageCount": max(1, -(-len(self.confirmed) // per))}}
        if path == "/next-api/competition/future-list":
            j = json.loads(fx("future.json"))
            page = params.get("page", 1)  # 2 páginas: a 2ª repete um evento (não pode duplicar)
            items = j["items"][:2] if page == 1 else j["items"][1:]
            return {"items": items, "_meta": {"pageCount": 2}}
        if path == "/next-api/competition/future-detail":
            self.detail_calls += 1
            return json.loads(fx("future.json"))["details"][str(params["id"])]
        if path == "/next-api/photographer-events/my-waiting-list":
            items = json.loads(fx("future.json"))["items"] if self.agenda_on else []
            items = [dict(items[2], waitingListStatus="pending"), dict(items[1], waitingListStatus="rejected")] if items else []
            return {"items": items, "_meta": {"pageCount": 1}}
        if path == "/next-api/photographer-events/schedule":
            self.schedule_ranges.append((params["from"], params["to"]))
            items = [dict(json.loads(fx("future.json"))["items"][0], userSignedToCompetition=True)] if self.agenda_on else []
            return {"items": items if params["from"] == date.today().isoformat() else [], "bounds": {}, "truncated": False}
        if path == "/next-api/report/sold-images":
            items = SOLD_ITEMS if params["type"] == "photo" else []
            return {"type": params["type"], "items": items, "pagination": {"pageCount": 1}}
        raise AssertionError(path)

    def download(self, path):
        self.downloads += 1
        return b"jpg"

    def login(self):
        pass

    def get(self, path, params=None):
        if path.startswith("/competition/information/"):
            return RANK_HTML
        if path == "/accounting/get-convertion-by-competition":
            return "<table><tr><th>Receita Media</th><th>Media de Fotos</th></tr><tr><td>R$ 1.200,00</td><td>184,92</td></tr></table>"
        if path == "/accounting/get-image-type-by-competition":
            return "<table><tr><td>Premium 4500 Pixels</td><td>158</td></tr><tr><td>Alta 3450 Pixels</td><td>43</td></tr><tr><td>TOTAL</td><td>201</td></tr></table>"
        if path == "/report/order-detail":
            return "<div><span>Nome do Cliente</span><span>Fulano</span><span>Total</span><span>R$ 19,90</span></div>"
        raise AssertionError(path)


class FlowTests(unittest.TestCase):
    def test_full_flow(self):
        import main
        from foco.telegram import Telegram
        state = {"geo": {"forquilhinha/sc": {"km": 230, "min": 180}, "itajaí/sc": {"km": 50, "min": 50},
                         "curitiba/pr": {"km": 220, "min": 170}}}
        tg = Telegram(state)
        sent = []
        tg.send = lambda t: sent.append(t)
        tg.photos = lambda urls, cap=None: sent.append(("fotos", len(urls), cap))
        tg.album = lambda items, cap=None: sent.append(
            ("album", ["sem marca" if i.get("data") else "miniatura" for i in items], cap))
        c = FakeClient()

        with mock.patch.object(events, "fetch_all", lambda client, **kw: future_events()):
            main.job_events(c, tg, state)                      # 1ª vez: resumo
            self.assertIn("Bot ligado", sent[-1])
            state["events"]["300003"]["status"] = "esgotado"   # simula mudança
            del state["events"]["300001"]                      # simula evento novo
            n = len(sent)
            main.job_events(c, tg, state)
            joined = "\n".join(x for x in sent[n:] if isinstance(x, str))
            self.assertIn("evento(s) novo(s)", joined)
            self.assertIn("abriu lista de espera", joined)

        main.job_sales(c, tg, state)                            # base
        self.assertIn("Monitor de vendas ligado", sent[-1])
        c.sales = sales_json(1520.0, 207)
        from datetime import datetime, timedelta
        t1 = datetime.utcnow() + timedelta(minutes=1)
        t2 = t1 + timedelta(minutes=2)
        f = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")
        c.confirmed = [confirmed(None, 11055904, "RRLL2699443", f(t2)),
                       confirmed(None, 11055461, "RRLL2699441", f(t1)),
                       confirmed(None, 11055461, "RRLL2699442", f(t1), "Alta 3450 Pixels", 5.0)] + c.confirmed
        local = (t1 - timedelta(hours=3)).strftime("%H:%M")
        n = len(sent)
        main.job_sales(c, tg, state)
        albums = [x for x in sent[n:] if x[0] == "album"]
        self.assertEqual(len(albums), 2)                       # um aviso por pedido
        self.assertIn("Pedido 11055461", albums[0][2])
        self.assertIn("1 Premium, 1 Alta", albums[0][2])
        self.assertIn(f"às {local} · Pix", albums[0][2])
        self.assertIn("Sua parte: <b>+R$ 12,40</b>", albums[0][2])
        self.assertIn("cliente pagou R$ 19,90", albums[0][2])
        self.assertIn("VILA GERMÂNICA", albums[0][2])
        self.assertIn("Média dos fotógrafos", albums[0][2])
        self.assertNotIn("Fulano", albums[0][2])
        self.assertEqual(albums[0][1], ["sem marca", "sem marca"])  # fotos baixadas do painel
        self.assertIn("Pedido 11055904", albums[1][2])
        # mesma venda de novo: nada é reenviado
        n = len(sent)
        self.assertEqual(main.job_sales(c, tg, state), 0)
        self.assertEqual(sent[n:], [])

        # sem evento em foco, o relatório não traz bloco detalhado
        n = len(sent)
        main.job_report(c, tg, state, save=False)
        self.assertFalse(any(isinstance(x, str) and "Vila Germânica –" in x for x in sent[n:]))
        # com evento em foco, traz
        main.FOCUS_EVENTS["269944"] = "Vila Germânica – Oktoberfest 2026"
        self.addCleanup(main.FOCUS_EVENTS.clear)
        main.job_report(c, tg, state)
        self.assertTrue(any(isinstance(x, str) and "Vila Germânica –" in x for x in sent[n:]))
        main.job_weekly(c, tg, state)
        self.assertIn("Resumo da semana", sent[-1])

        # agenda e comandos
        c.agenda_on = True
        n = len(sent)
        main.handle_command("/agenda", c, tg, state)
        self.assertIn("Sua agenda", sent[-1])
        self.assertIn("✅", sent[-1]); self.assertIn("⏳", sent[-1])
        self.assertIn("🏆 27º de 63 fotógrafos", sent[-1])
        self.assertEqual(sent[-1].count("🏆"), 1)  # só no confirmado, não na lista de espera
        snap = dict(state["report_snapshot"])
        main.handle_command("relatório", c, tg, state)
        self.assertEqual(state["report_snapshot"], snap)  # sob demanda não mexe no relatório das 9h
        self.assertTrue(any("Relatório agora" in x for x in sent[n:] if isinstance(x, str)))
        with mock.patch.object(events, "fetch_all", lambda client, **kw: future_events()):
            main.handle_command("/eventos", c, tg, state)
        self.assertNotIn("CORRIDA DO CORAÇÃO", sent[-1])  # já inscrito: não recomenda de novo
        main.handle_command("qualquer coisa", c, tg, state)
        self.assertIn("Não entendi", sent[-1])

        # aprovado na lista de espera
        state["agenda"] = {"300001": {"mine": "espera", "title": "CORRIDA DO CORAÇÃO", "date": "2030-10-17"}}
        main.check_agenda_changes(main.get_agenda(c, state), tg, state)
        self.assertIn("Você foi aprovado", sent[-1])

    def test_history_never_becomes_alert(self):
        """Regressão: histórico em várias páginas não pode virar enxurrada de 'venda nova'."""
        import main
        from datetime import datetime, timedelta
        from foco.telegram import Telegram
        state, sent = {}, []
        tg = Telegram(state)
        tg.send = lambda t: sent.append(t)
        tg.album = lambda items, cap=None: sent.append(("album", cap))
        c = FakeClient()
        base = datetime.utcnow() - timedelta(hours=1)
        stamp = lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S")
        # 300 fotos antigas (6 páginas), a mais nova há 1h
        c.confirmed = [confirmed(None, 11000000 - k, f"RRLL269944{k:05d}", stamp(base - timedelta(minutes=10 * k)))
                       for k in range(300)]
        main.job_sales(c, tg, state)
        self.assertEqual(len(sent), 1)                       # só "monitor ligado"
        for _ in range(3):
            self.assertEqual(main.job_sales(c, tg, state), 0)
        self.assertEqual(len(sent), 1)
        # entra 1 venda nova: 1 aviso
        c.confirmed.insert(0, confirmed(None, 11999999, "RRLL2699443", stamp(datetime.utcnow())))
        self.assertEqual(main.job_sales(c, tg, state), 1)
        self.assertEqual(len(sent), 2)
        self.assertIn("Pedido 11999999", sent[-1][1])
        # muitas de uma vez: um resumo só
        c.confirmed[:0] = [confirmed(None, 12000000 + k, f"RRLL269944X{k}", stamp(datetime.utcnow())) for k in range(20)]
        main.job_sales(c, tg, state)
        self.assertEqual(len(sent), 3)
        self.assertIn("20 pedidos novos", sent[-1])

    def test_old_memory_starts_silently(self):
        import main
        from foco.telegram import Telegram
        state, sent = {"seen_sales": ["1|x"]}, []
        tg = Telegram(state)
        tg.send = lambda t: sent.append(t)
        tg.album = lambda items, cap=None: sent.append(cap)
        c = FakeClient()
        c.confirmed = [confirmed(None, 5, "RRLL2699445", "2026-01-01 10:00:00")]
        self.assertEqual(main.job_sales(c, tg, state), 0)
        self.assertEqual(main.job_sales(c, tg, state), 0)
        self.assertEqual(sent, [])

    def test_cookie_header(self):
        from foco.client import FocoClient, parse_cookie_header
        self.assertEqual(parse_cookie_header("cookie: a=1; b=x=y=="), {"a": "1", "b": "x=y=="})
        c = FocoClient(cookie="a=1")
        self.assertEqual(c.s.cookies.get("a", domain="www.focomarket.com.br"), "1")

    def _client_with_page(self, url):
        from foco.client import FocoClient
        c = FocoClient(cookie="a=1")
        c.s = mock.Mock(cookies=c.s.cookies)
        c.s.get.return_value = mock.Mock(url=url)
        return c

    def test_expired_session_never_posts_and_stops_trying(self):
        from foco.client import LoginError
        c = self._client_with_page("https://www.focomarket.com.br/site/login")
        for _ in range(3):
            with self.assertRaises(LoginError):
                c.login()
        self.assertTrue(c.expired)
        self.assertEqual(c.s.get.call_count, 1)  # só a primeira vai ao site
        c.s.post.assert_not_called()

    def test_valid_session(self):
        c = self._client_with_page("https://www.focomarket.com.br/competition/future")
        c.login()
        self.assertTrue(c.logged)
        self.assertFalse(c.expired)

    def test_expired_session_alerts_once_until_it_returns(self):
        import main
        from foco.client import LoginError
        c = mock.Mock(expired=True, logged=False)
        tg = mock.Mock()
        state = {"done": {}}
        with mock.patch.object(main, "job_sales", side_effect=LoginError("x")), \
                mock.patch.object(main, "job_events", side_effect=LoginError("x")), \
                mock.patch.object(main, "job_report", side_effect=LoginError("x")), \
                mock.patch.object(main, "job_weekly", side_effect=LoginError("x")):
            main.job_auto(c, tg, state, commands=False)
            main.job_auto(c, tg, state, commands=False)
            self.assertEqual(tg.send.call_count, 1)
            self.assertIn("venceu", tg.send.call_args[0][0])
            # cookie renovado: volta a funcionar e um novo vencimento avisa de novo
            main.job_auto(mock.Mock(expired=False, logged=True), tg, state, commands=False)
            self.assertFalse(state["session_alerted"])
            main.job_auto(c, tg, state, commands=False)
            self.assertEqual(tg.send.call_count, 2)

    def test_conflict(self):
        import main
        evs = [{"id": "1", "date": "2026-10-17"}, {"id": "2", "date": "2026-10-18"}]
        agenda = {"9": {"id": "9", "date": "2026-10-17", "title": "MARATONA DE POMERODE 6KM", "mine": "inscrito"}}
        main.mark_agenda(evs, agenda)
        self.assertEqual(evs[0]["conflicts"], ["Maratona De Pomerode 6Km"])
        self.assertEqual(evs[1]["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
