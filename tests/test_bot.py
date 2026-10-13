"""Testes offline: python -m unittest discover tests"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DRY_RUN"] = "1"

from foco import events, sales  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")


def fx(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


SALES_HTML = """<table><thead><tr><th>Evento</th></tr></thead><tbody>
<tr><td>255342 - OKTOBERFEST RUN 2026</td><td>11/10/2026</td><td>R$ 1.000,00</td><td>R$ 1.000,00</td><td>127</td><td><a>x</a></td></tr>
<tr><td>269944 - VILA GERMÂNICA 41ª OKTOBERFEST BLUMENAU 2026</td><td>07/10/2026</td><td>R$ 1.500,00</td><td>R$ 1.500,00</td><td>204</td><td></td></tr>
<tr><td>TOTAL</td><td></td><td>R$ 2.500,00</td><td></td><td>331</td></tr>
</tbody></table>"""

SOLD_HTML = """<div id="w5-tab0"><table><tbody>
<tr><td>11055461</td><td>Premium 4500 Pixels</td><td>RRLL1</td><td><img src="https://cdn/x/RRLL1.jpg"></td><td>22:11:21</td><td>Ver</td></tr>
<tr><td></td><td>Alta 3450 Pixels</td><td>RRLL2</td><td><img src="https://cdn/x/RRLL2.jpg"></td><td>20:05:00</td><td>Ver</td></tr>
<tr><td>11055904</td><td>Premium 4500 Pixels</td><td>RRLL3</td><td><img src="https://cdn/x/RRLL3.jpg"></td><td>20:40:00</td><td>Ver</td></tr>
</tbody></table></div>"""


class ParseTests(unittest.TestCase):
    def test_future(self):
        evs = {e["id"]: e for e in events.parse_future(fx("future.html"))}
        self.assertEqual(len(evs), 3)
        a = evs["300001"]
        self.assertEqual((a["city"], a["uf"], a["sport"]), ("Forquilhinha", "SC", "Corrida de Rua"))
        self.assertEqual(a["status"], "aberto")
        self.assertEqual(a["vagas"], 4)
        self.assertEqual(a["photographers"], 12)
        self.assertEqual(a["commission"], 90)
        self.assertEqual(a["price_premium"], 19.90)
        self.assertEqual(a["partnership"], "oficial")
        self.assertEqual(a["date"], "2026-10-17")
        b = evs["275615"]
        self.assertEqual(b["status"], "espera_encerrada")  # texto do modal não confunde
        self.assertEqual(b["waitlist"], 18)
        c = evs["300003"]
        self.assertEqual((c["status"], c["uf"], c["partnership"]), ("espera", "PR", "sem"))

    def test_relevance(self):
        evs = {e["id"]: e for e in events.parse_future(fx("future.html"))}
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
        s = sales.parse_sales_table(SALES_HTML)
        self.assertEqual(set(s), {"255342", "269944"})
        self.assertAlmostEqual(s["269944"]["revenue"], 1500.00)
        self.assertEqual(s["269944"]["photos"], 204)

    def test_agenda_card_without_modal(self):
        evs = events.parse_future(AGENDA_DAY_HTML)
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0]["id"], evs[0]["city"], evs[0]["date"]), ("193965", "Blumenau", "2026-11-08"))

    def test_sold(self):
        rows = sales.parse_sold_images(SOLD_HTML)
        self.assertEqual([r["order"] for r in rows], ["11055461", "11055461", "11055904"])
        self.assertEqual(sales.hour_histogram(rows)[20], 2)
        ppo, _ = sales.photos_per_order(rows)
        self.assertAlmostEqual(ppo, 1.5)


AGENDA_DAY_HTML = """<div class="col-md-6 col-sm-12 card-event-widget"><div class="event-card-fc ">
<div class="event-card-header-fc"><h3 class="event-title-fc">CIRCUITO ANGELONI 2026 - BLUMENAU</h3>
<a class="event-dropdown-link-fc" href="/competition/update-spot?id=193965">Editar</a>
<a class="link-event" id="link-event-193965" href="https://www.focoradical.com.br/evento/x"></a></div>
<div class="event-card-body"><div class="event-information-container"><div class="left-card-column">
<div class="icon-text-card"><span class="event-text-fc event-city-fc">Corrida de Rua</span></div>
<div class="icon-text-card icon-text-card-location-fc"><span class="event-text-fc"><span class="event-city-fc">Blumenau</span><span class="event-state-fc">/ SC</span></span></div>
</div><div>08/11/26</div></div>
<button class="event-button-fc" data-target="#view-event-modal-193965">Ver Evento</button>
<a href="/competition/information/193965#uploads">Uploads</a>
<button data-competition_id="193965">Informações</button></div></div></div>"""


class FakeClient:
    """Simula o site: vendas crescem entre as chamadas."""
    def __init__(self):
        self.sales_html = SALES_HTML
        self.agenda_on = False

    def login(self):
        pass

    def get(self, path, params=None):
        if path == "/competition/future":
            return fx("future.html")
        if path == "/competition/my-waiting-list":
            if not self.agenda_on:
                return "<html></html>"
            return fx("future.html").split('<div class="col-md-4 col-sm-12 card-event-widget">')[0] + \
                '<div class="col-md-4 col-sm-12 card-event-widget">' + fx("future.html").split('<div class="col-md-4 col-sm-12 card-event-widget">')[3]
        if path == "/competition/schedule":
            if not self.agenda_on:
                return "<html></html>"
            return '<div class="time-frame" data-time-frame-index="2026-10-17" data-total-competitions="1"></div>' \
                   '<div class="time-frame" data-time-frame-index="2026-10-18" data-total-competitions="0"></div>' \
                   '<div class="time-frame" data-time-frame-index="2020-01-01" data-total-competitions="3"></div>'
        if path == "/competition/load-competitions-by-date":
            assert params["date"] == "2026-10-17", params
            parts = fx("future.html").split('<div class="col-md-4 col-sm-12 card-event-widget">')
            return parts[0] + '<div class="col-md-4 col-sm-12 card-event-widget">' + parts[1]
        if path == "/accounting/orders-by-competition-by-user":
            return self.sales_html
        if path == "/report/sold-images":
            return SOLD_HTML if (params or {}).get("page-photo", 1) == 1 else "<table></table>"
        if path == "/accounting/get-convertion-by-competition":
            return "<table><tr><th>Receita Media</th><th>Media de Fotos</th></tr><tr><td>R$ 1.200,00</td><td>184,92</td></tr></table>"
        if path == "/accounting/get-image-type-by-competition":
            return "<table><tr><td>Premium 4500 Pixels</td><td>158</td><td>R$ 2.000,00</td></tr><tr><td>Alta 3450 Pixels</td><td>43</td><td>R$ 500,00</td></tr><tr><td>TOTAL</td><td>201</td><td>R$ 1,00</td></tr></table>"
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
        c = FakeClient()

        with mock.patch.object(events, "fetch_all", lambda client: events.parse_future(fx("future.html"))):
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
        c.sales_html = SALES_HTML.replace("R$ 1.500,00</td><td>R$ 1.500,00</td><td>204", "R$ 1.520,00</td><td>R$ 1.520,00</td><td>206")
        state["sold_codes"]["269944"] = ["11055461|https://cdn/x/RRLL1.jpg"]
        n = len(sent)
        main.job_sales(c, tg, state)
        albums = [x for x in sent[n:] if x[0] == "fotos"]
        self.assertEqual(len(albums), 2)                       # um aviso por pedido
        self.assertIn("Pedido 11055461", albums[0][2])
        self.assertEqual(albums[0][1], 1)                      # só a foto nova desse pedido
        self.assertIn("Pedido 11055904", albums[1][2])
        self.assertIn("2 pedidos", albums[1][2])
        # mesma venda de novo: nada é reenviado
        c.sales_html = c.sales_html.replace("1.520,00</td><td>R$ 1.520,00</td><td>206", "1.530,00</td><td>R$ 1.530,00</td><td>207")
        n = len(sent)
        main.job_sales(c, tg, state)
        self.assertEqual(sent[n:], [])                         # espera a foto aparecer
        self.assertEqual(state["sales"]["269944"]["photos"], 206)
        for _ in range(3):
            main.job_sales(c, tg, state)
        self.assertFalse([x for x in sent[n:] if x[0] == "fotos"])  # nunca reenvia fotos antigas
        self.assertEqual(state["sales"]["269944"]["photos"], 207)

        main.job_report(c, tg, state)
        self.assertTrue(any(isinstance(x, str) and "Vila Germânica" in x for x in sent))
        main.job_weekly(c, tg, state)
        self.assertIn("Resumo da semana", sent[-1])

        # agenda e comandos
        c.agenda_on = True
        n = len(sent)
        main.handle_command("/agenda", c, tg, state)
        self.assertIn("Sua agenda", sent[-1])
        self.assertIn("✅", sent[-1]); self.assertIn("⏳", sent[-1])
        snap = dict(state["report_snapshot"])
        main.handle_command("relatório", c, tg, state)
        self.assertEqual(state["report_snapshot"], snap)  # sob demanda não mexe no relatório das 9h
        self.assertTrue(any("Relatório agora" in x for x in sent[n:] if isinstance(x, str)))
        with mock.patch.object(events, "fetch_all", lambda client: events.parse_future(fx("future.html"))):
            main.handle_command("/eventos", c, tg, state)
        self.assertNotIn("CORRIDA DO CORAÇÃO", sent[-1])  # já inscrito: não recomenda de novo
        main.handle_command("qualquer coisa", c, tg, state)
        self.assertIn("Não entendi", sent[-1])

        # aprovado na lista de espera
        state["agenda"] = {"300001": {"mine": "espera", "title": "CORRIDA DO CORAÇÃO", "date": "2026-10-17"}}
        main.check_agenda_changes(main.get_agenda(c, state), tg, state)
        self.assertIn("Você foi aprovado", sent[-1])

    def test_conflict(self):
        import main
        evs = [{"id": "1", "date": "2026-10-17"}, {"id": "2", "date": "2026-10-18"}]
        agenda = {"9": {"id": "9", "date": "2026-10-17", "title": "MARATONA DE POMERODE 6KM", "mine": "inscrito"}}
        main.mark_agenda(evs, agenda)
        self.assertEqual(evs[0]["conflicts"], ["Maratona De Pomerode 6Km"])
        self.assertEqual(evs[1]["conflicts"], [])


if __name__ == "__main__":
    unittest.main()
