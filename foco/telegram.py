"""Envio para o Telegram. Sem token configurado, só imprime no terminal (modo teste)."""
import json
import os
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, state):
        self.token = os.environ.get("TELEGRAM_TOKEN", "").strip()
        self.state = state
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or state.get("telegram_chat_id")
        self.dry = not self.token or os.environ.get("DRY_RUN") == "1"

    def _call(self, method, **payload):
        r = requests.post(API.format(token=self.token, method=method), json=payload, timeout=30)
        data = r.json()
        if not data.get("ok") and data.get("error_code") == 429:
            time.sleep(data.get("parameters", {}).get("retry_after", 5))
            r = requests.post(API.format(token=self.token, method=method), json=payload, timeout=30)
            data = r.json()
        return data

    def _upload(self, method, data, files):
        url = API.format(token=self.token, method=method)
        for _ in range(2):
            try:
                r = requests.post(url, data=data, files=files, timeout=180)
                out = r.json()
            except (requests.RequestException, ValueError) as ex:
                out = {"ok": False, "description": str(ex)}
            if not out.get("ok") and out.get("error_code") == 429:
                time.sleep(out.get("parameters", {}).get("retry_after", 5))
                continue
            return out
        return out

    def ensure_chat(self):
        """Descobre o chat_id sozinho: basta mandar qualquer mensagem pro bot uma vez."""
        if self.dry or self.chat_id:
            return True
        data = self._call("getUpdates")
        for upd in reversed(data.get("result", [])):
            msg = upd.get("message") or upd.get("my_chat_member") or {}
            chat = msg.get("chat")
            if chat:
                self.chat_id = str(chat["id"])
                self.state["telegram_chat_id"] = self.chat_id
                self.send("✅ Bot da Foco conectado! A partir de agora você recebe eventos, vendas e relatórios aqui.")
                return True
        print("⚠️  Telegram: mande um 'oi' para o seu bot para ele descobrir seu chat.")
        return False

    def updates(self, timeout=0):
        """Mensagens novas que você mandou pro bot (comandos)."""
        if self.dry:
            return []
        offset = self.state.get("tg_offset", 0)
        try:
            r = requests.post(API.format(token=self.token, method="getUpdates"),
                              json={"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
                              timeout=timeout + 15)
            data = r.json().get("result", [])
        except requests.RequestException:
            return []
        msgs = []
        for upd in data:
            self.state["tg_offset"] = upd["update_id"] + 1
            msg = upd.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id", ""))
            if not self.chat_id and chat:
                self.chat_id = chat
                self.state["telegram_chat_id"] = chat
            if chat and chat == str(self.chat_id) and msg.get("text"):
                msgs.append(msg["text"].strip())
        return msgs

    def typing(self):
        if not self.dry and self.chat_id:
            self._call("sendChatAction", chat_id=self.chat_id, action="typing")

    def send(self, text):
        if self.dry:
            print("\n" + "=" * 60 + "\n" + text)
            return
        if not self.ensure_chat():
            return
        # Telegram aceita até 4096 caracteres por mensagem
        while text:
            chunk, text = text[:4000], text[4000:]
            if text:
                cut = chunk.rfind("\n\n")
                if cut > 1000:
                    text = chunk[cut:] + text
                    chunk = chunk[:cut]
            self._call("sendMessage", chat_id=self.chat_id, text=chunk, parse_mode="HTML",
                       disable_web_page_preview=True)

    def photos(self, urls, caption=None):
        urls = [u for u in urls if u][:10]
        if not urls:
            return
        if self.dry:
            print(f"[{len(urls)} fotos] {caption or ''}\n  " + "\n  ".join(urls))
            return
        if not self.ensure_chat():
            return
        media = [{"type": "photo", "media": u} for u in urls]
        if caption:
            media[0]["caption"] = caption
            media[0]["parse_mode"] = "HTML"
        if len(media) == 1:
            self._call("sendPhoto", chat_id=self.chat_id, photo=urls[0], caption=caption or "", parse_mode="HTML")
        else:
            self._call("sendMediaGroup", chat_id=self.chat_id, media=media)

    def album(self, items, caption=None):
        """Álbum com arquivos baixados do painel (fotos sem marca d'água / vídeos).
        items: [{"data": bytes|None, "url": miniatura pública (plano B), "video": bool}]"""
        items = [i for i in items if i.get("data") or i.get("url")][:10]
        caption = (caption or "")[:1024]
        if not items:
            if caption:
                self.send(caption)
            return
        if self.dry:
            kinds = ["vídeo" if i.get("video") and i.get("data") else ("sem marca" if i.get("data") else "miniatura")
                     for i in items]
            print(f"[{len(items)} arquivos: {', '.join(kinds)}] {caption}")
            return
        if not self.ensure_chat():
            return
        media, files = [], {}
        for n, it in enumerate(items):
            kind = "video" if it.get("video") and it.get("data") else "photo"
            if it.get("data"):
                name = f"f{n}"
                files[name] = (f"{name}.{'mp4' if kind == 'video' else 'jpg'}", it["data"],
                               "video/mp4" if kind == "video" else "image/jpeg")
                media.append({"type": kind, "media": f"attach://{name}"})
            else:
                media.append({"type": "photo", "media": it["url"]})
        if caption:
            media[0].update(caption=caption, parse_mode="HTML")
        if len(media) == 1:
            m = media[0]
            method = "sendVideo" if m["type"] == "video" else "sendPhoto"
            field = "video" if m["type"] == "video" else "photo"
            data = {"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"}
            if files:
                out = self._upload(method, data, {field: next(iter(files.values()))})
            else:
                out = self._call(method, chat_id=self.chat_id, caption=caption, parse_mode="HTML", **{field: m["media"]})
        else:
            out = self._upload("sendMediaGroup", {"chat_id": self.chat_id, "media": json.dumps(media)}, files)
        if not out.get("ok"):
            # foto recusada (tamanho/formato): manda pelo menos o texto e as miniaturas
            print("Telegram recusou o álbum:", (out.get("description") or "")[:200])
            thumbs = [i["url"] for i in items if i.get("url")]
            if thumbs:
                self.photos(thumbs, caption)
            elif caption:
                self.send(caption)
