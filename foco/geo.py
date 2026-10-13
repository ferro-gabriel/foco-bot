"""Distância de carro a partir de Blumenau (OpenStreetMap, com cache no estado)."""
import math
import time

import requests

from . import config

UA = {"User-Agent": "foco-bot/1.0 (fotografo Blumenau)"}


def _haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def geocode(city, uf):
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"city": city, "state": uf, "country": "Brasil", "format": "json", "limit": 1},
        headers=UA,
        timeout=20,
    )
    time.sleep(1.1)  # regra de uso do Nominatim
    data = r.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def route(a, b):
    try:
        r = requests.get(
            f"https://router.project-osrm.org/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}",
            params={"overview": "false"},
            headers=UA,
            timeout=20,
        )
        rt = r.json()["routes"][0]
        return round(rt["distance"] / 1000), round(rt["duration"] / 60)
    except Exception:
        km = round(_haversine(a, b) * 1.3)  # estimativa estrada ≈ 1,3× linha reta
        return km, round(km / 75 * 60)


def distance(city, uf, cache):
    key = f"{city}/{uf}".lower()
    if key in cache:
        return cache[key]
    result = {"km": None, "min": None}
    try:
        pt = geocode(city, uf)
        if pt:
            km, mins = route(config.HOME_LATLON, pt)
            result = {"km": km, "min": mins}
    except Exception:
        pass
    cache[key] = result
    return result
