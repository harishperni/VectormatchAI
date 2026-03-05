from __future__ import annotations

import math
import urllib.parse
import urllib.request
from functools import lru_cache

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ATS-Talent-Intelligence/0.1 (local-dev)"

FALLBACK_COORDS: dict[str, tuple[float, float]] = {
    "oakland park, fl": (26.1723, -80.1319),
    "nashville, tn": (36.1627, -86.7816),
    "peoria, il": (40.6936, -89.5890),
    "bangalore, india": (12.9716, 77.5946),
    "pune, india": (18.5204, 73.8567),
    "chennai, india": (13.0827, 80.2707),
    "san jose, ca": (37.3382, -121.8863),
    "san francisco, ca": (37.7749, -122.4194),
    "los angeles, ca": (34.0522, -118.2437),
    "seattle, wa": (47.6062, -122.3321),
    "austin, tx": (30.2672, -97.7431),
    "dallas, tx": (32.7767, -96.7970),
    "new york, ny": (40.7128, -74.0060),
    "chicago, il": (41.8781, -87.6298),
    "boston, ma": (42.3601, -71.0589),
    "atlanta, ga": (33.7490, -84.3880),
    "phoenix, az": (33.4484, -112.0740),
    "denver, co": (39.7392, -104.9903),
    "miami, fl": (25.7617, -80.1918),
    "san diego, ca": (32.7157, -117.1611),
}


def _normalize(location: str | None) -> str | None:
    if not location:
        return None
    value = " ".join(location.strip().split())
    return value or None


def _normalize_city_state(location: str) -> str:
    value = location.lower().replace(" united states", "").replace(" usa", "").replace(" us", "")
    return " ".join(value.split()).strip(" ,")


@lru_cache(maxsize=512)
def geocode_location(location: str) -> tuple[float, float] | None:
    normalized = _normalize(location)
    if not normalized:
        return None
    key = _normalize_city_state(normalized)
    if key in FALLBACK_COORDS:
        return FALLBACK_COORDS[key]

    params = urllib.parse.urlencode({"q": normalized, "format": "jsonv2", "limit": 1})
    url = f"{NOMINATIM_URL}?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = response.read().decode("utf-8")
    except Exception:
        return None

    import json

    try:
        data = json.loads(payload)
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    first = data[0]
    if not isinstance(first, dict):
        return None

    lat = first.get("lat")
    lon = first.get("lon")
    try:
        return (float(lat), float(lon))
    except Exception:
        return None


def _haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    r_miles = 3958.8
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance = 2 * r_miles * math.asin(math.sqrt(hav))
    return round(distance, 2)


def distance_miles_between(job_location: str | None, candidate_location: str | None) -> float | None:
    job_loc = _normalize(job_location)
    cand_loc = _normalize(candidate_location)
    if not job_loc or not cand_loc:
        return None

    if job_loc.lower() == cand_loc.lower():
        return 0.0

    # Fast fallback: same city/state text prefix before geocoding.
    if job_loc.split(",")[0].strip().lower() == cand_loc.split(",")[0].strip().lower():
        return 0.0

    job_geo = geocode_location(job_loc)
    cand_geo = geocode_location(cand_loc)
    if not job_geo or not cand_geo:
        return None

    return _haversine_miles(job_geo, cand_geo)
