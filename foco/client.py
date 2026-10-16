"""Sessão autenticada no FocoMarket (painel do fotógrafo)."""
import os
import re
import time

import requests

BASE = "https://www.focomarket.com.br"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


class LoginError(RuntimeError):
    pass


class FocoClient:
    def __init__(self, username=None, password=None):
        self.username = username or os.environ.get("FOCO_USER", "")
        self.password = password or os.environ.get("FOCO_PASSWORD", "")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.logged = False

    def login(self):
        if not self.username or not self.password:
            raise LoginError("FOCO_USER / FOCO_PASSWORD não configurados")
        r = self.s.get(BASE + "/site/login", timeout=30)
        m = re.search(r'name="_csrf" value="([^"]+)"', r.text)
        if not m:
            raise LoginError("Não achei o token _csrf na página de login")
        r = self.s.post(
            BASE + "/site/login",
            data={
                "_csrf": m.group(1),
                "LoginForm[username]": self.username,
                "LoginForm[password]": self.password,
                "LoginForm[rememberMe]": "1",
            },
            timeout=30,
        )
        if "/site/login" in r.url or 'id="loginform"' in r.text:
            if "captcha" in r.text.lower() and "loginform-captcha" in r.text:
                raise LoginError("O site pediu captcha. Entre uma vez pelo navegador e tente de novo mais tarde.")
            raise LoginError("Login recusado: confira usuário e senha")
        self.logged = True

    def get(self, path, params=None, retries=2):
        if not self.logged:
            self.login()
        for attempt in range(retries + 1):
            try:
                r = self.s.get(BASE + path, params=params, timeout=40)
                if "/site/login" in r.url:  # sessão caiu
                    self.logged = False
                    self.login()
                    continue
                r.raise_for_status()
                return r.text
            except requests.RequestException:
                if attempt == retries:
                    raise
                time.sleep(3 * (attempt + 1))
        raise LoginError("Não consegui manter a sessão")

    def get_json(self, path, params=None, retries=2):
        """Telas novas do painel (/next-api/...). Sem sessão a API responde 401/403/404."""
        if not self.logged:
            self.login()
        relogged = False
        for attempt in range(retries + 1):
            try:
                r = self.s.get(BASE + path, params=params, timeout=40, headers={"Accept": "application/json"})
                if (r.status_code in (401, 403, 404) or "/site/login" in r.url) and not relogged:
                    relogged = True
                    self.logged = False
                    self.login()
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError):
                if attempt == retries:
                    raise
                time.sleep(3 * (attempt + 1))
        raise LoginError(f"API do painel não respondeu: {path}")

    def download(self, path, max_bytes=45_000_000):
        """Arquivo do painel (ex.: foto vendida sem marca d'água). None se falhar ou for grande demais."""
        if not self.logged:
            self.login()
        url = path if path.startswith("http") else BASE + path
        try:
            with self.s.get(url, timeout=90, stream=True) as r:
                if r.status_code != 200 or "text/html" in r.headers.get("content-type", ""):
                    return None
                if int(r.headers.get("content-length") or 0) > max_bytes:
                    return None
                data = b""
                for chunk in r.iter_content(256 * 1024):
                    data += chunk
                    if len(data) > max_bytes:
                        return None
                return data or None
        except requests.RequestException:
            return None
