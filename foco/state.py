"""Memória do bot. No GitHub fica criptografada (state.enc) com a chave STATE_KEY."""
import json
import os

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")
PLAIN = os.path.join(DIR, "state.json")
ENC = os.path.join(DIR, "state.enc")


def _fernet():
    key = os.environ.get("STATE_KEY", "").strip()
    if not key:
        return None
    from cryptography.fernet import Fernet
    return Fernet(key.encode())


def load():
    f = _fernet()
    try:
        if f and os.path.exists(ENC):
            with open(ENC, "rb") as fh:
                return json.loads(f.decrypt(fh.read()))
        with open(PLAIN, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(state):
    os.makedirs(DIR, exist_ok=True)
    data = json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True).encode()
    f = _fernet()
    path, payload = (ENC, f.encrypt(data)) if f else (PLAIN, data)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, path)
