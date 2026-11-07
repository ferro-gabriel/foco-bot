"""Sessão autenticada no FocoMarket (painel do fotógrafo)."""
import os
import time

import requests

DOMAIN = "www.focomarket.com.br"
BASE = "https://" + DOMAIN
EXPIRED_MSG = "A sessão da Foco venceu: renove o FOCO_COOKIE"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


class LoginError(RuntimeError):
    pass


def parse_cookie_header(raw):
    """'a=1; b=2' (o cabeçalho Cookie copiado do navegador) vira {'a': '1', 'b': '2'}."""
    raw = (raw or "").strip()
    if raw.lower().startswith("cookie:"):
        raw = raw[len("cookie:"):]
    pairs = (p.split("=", 1) for p in raw.split(";") if "=" in p)
    return {k.strip(): v.strip() for k, v in pairs if k.strip()}


class FocoClient:
    """O login do site exige captcha, então o bot usa a sessão aberta por você no navegador
    (secret FOCO_COOKIE) e nunca envia usuário e senha."""

    def __init__(self, cookie=None):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        # presos ao domínio da Foco: não vão junto em requisições para outros endereços
        for name, value in parse_cookie_header(cookie or os.environ.get("FOCO_COOKIE", "")).items():
            self.s.cookies.set(name, value, domain=DOMAIN, path="/")
        self.logged = False
        self.expired = False  # sessão recusada: não insiste até o cookie ser renovado

    def login(self):
        """Confere se a sessão ainda vale. Falha de rede sobe como RequestException, não como sessão vencida."""
        if self.expired:
            raise LoginError(EXPIRED_MSG)
        if not self.s.cookies:
            self.expired = True
            raise LoginError("FOCO_COOKIE não configurado")
        r = self.s.get(BASE + "/competition/future", timeout=30)
        if "/site/login" in r.url or "/code-access" in r.url:
            self.expired = True
            raise LoginError(EXPIRED_MSG)
        r.raise_for_status()
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
