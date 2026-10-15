"""
Turns a plain-language place (village, area, city, country) into map
coordinates, so nobody has to know their latitude / longitude.

Uses OpenStreetMap's free Nominatim service. If it can't be reached
(no internet, rate limit...) every function returns None and the caller
decides what to do -- nothing here ever raises.
"""
from typing import Optional, Tuple

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_HEADERS = {"User-Agent": "LifeFlow-BloodNetwork/2.1 (contact: admin@lifeflow.com)"}


def build_address_label(village=None, area=None, city=None, state=None, country=None) -> str:
    return ", ".join(p.strip() for p in (village, area, city, state, country) if p and str(p).strip())


def geocode_place(village=None, area=None, city=None, state=None, country=None) -> Optional[Tuple[float, float]]:
    """Tries the most specific address first, then falls back to broader ones."""
    attempts = [
        (village, area, city, state, country),
        (area, city, state, country),
        (village, city, state, country),
        (city, state, country),
        (city, country),
    ]
    seen = set()
    for parts in attempts:
        query = ", ".join(p.strip() for p in parts if p and str(p).strip())
        if not query or query in seen:
            continue
        seen.add(query)
        try:
            response = requests.get(
                NOMINATIM_URL,
                params={"q": query, "format": "json", "limit": 1},
                headers=_HEADERS,
                timeout=6,
            )
            if response.status_code == 200 and response.json():
                hit = response.json()[0]
                return float(hit["lat"]), float(hit["lon"])
        except Exception:  # noqa: BLE001
            return None
    return None
