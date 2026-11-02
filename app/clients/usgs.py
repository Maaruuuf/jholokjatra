"""USGS earthquake feed (GeoJSON)."""
import datetime as dt

import httpx

from ..config import get_settings
from ..domain import Quake
from ..geo import haversine_km
from ..http import Fetched, fetch_json

URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


async def get_quakes(client: httpx.AsyncClient, lat: float, lon: float, since: dt.date,
                     radius_km: int = 300, min_mag: float = 4.5, until: dt.date | None = None) -> Fetched:
    return await fetch_json(client, URL, {
        "format": "geojson", "latitude": lat, "longitude": lon, "maxradiuskm": radius_km,
        "starttime": since.isoformat(), "endtime": until.isoformat() if until else None,
        "minmagnitude": min_mag, "orderby": "time"}, ttl=get_settings().ttl_quakes)


def parse_quakes(fetched: Fetched, lat: float, lon: float) -> list[Quake]:
    out: list[Quake] = []
    for f in (fetched.data or {}).get("features", []):
        try:
            p = f["properties"]
            lon2, lat2 = f["geometry"]["coordinates"][:2]
            day = dt.datetime.fromtimestamp(p["time"] / 1000, tz=dt.timezone.utc).date()
            out.append(Quake(float(p["mag"]), str(p.get("place", "")), day,
                             round(haversine_km(lat, lon, lat2, lon2), 1), p.get("url") or fetched_url(fetched), fetched.ref))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fetched_url(f: Fetched) -> str:
    return f.url
