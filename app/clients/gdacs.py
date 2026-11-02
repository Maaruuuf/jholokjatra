"""GDACS (UN/EC Global Disaster Alert and Coordination System): cyclone and flood alerts.

NOTE: the response is GeoJSON-like. Parsing is deliberately defensive; run
`python scripts/smoke_test_apis.py` once to confirm the shape on your network.
"""
import datetime as dt
import logging

import httpx

from ..config import get_settings
from ..domain import Alert
from ..geo import haversine_km
from ..http import Fetched, fetch_json

log = logging.getLogger("jholokjatra.gdacs")
SEARCH_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"


async def get_events(client: httpx.AsyncClient, start: dt.date, end: dt.date, ttl: int | None = None) -> Fetched:
    return await fetch_json(client, SEARCH_URL, {
        "eventlist": "TC;FL", "fromdate": start.isoformat(), "todate": end.isoformat(),
        "alertlevel": "green;orange;red"}, ttl=ttl if ttl is not None else get_settings().ttl_alerts)


def _d(value, default: dt.date) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return default


def parse_events(fetched: Fetched, lat: float, lon: float, max_km: float = 800) -> list[Alert]:
    data = fetched.data if isinstance(fetched.data, dict) else {}
    feats = data.get("features")
    if feats is None:
        log.warning("GDACS response has no 'features' key; shape may have changed")
        return []
    out: list[Alert] = []
    for f in feats:
        try:
            p = f.get("properties", {})
            kind = str(p.get("eventtype", "")).upper()
            if kind not in ("TC", "FL"):
                continue
            lon2, lat2 = f["geometry"]["coordinates"][:2]
            dist = haversine_km(lat, lon, float(lat2), float(lon2))
            if dist > max_km:
                continue
            today = dt.date.today()
            url = p.get("url", {}).get("report") if isinstance(p.get("url"), dict) else p.get("url")
            out.append(Alert(
                kind=kind, name=str(p.get("name") or p.get("eventname") or kind), level=str(p.get("alertlevel", "Green")).title(),
                lat=float(lat2), lon=float(lon2), start=_d(p.get("fromdate"), today), end=_d(p.get("todate"), today),
                distance_km=round(dist, 1), url=url or fetched.url, ref=fetched.ref))
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out
