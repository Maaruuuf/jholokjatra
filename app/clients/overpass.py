"""OpenStreetMap Overpass: nearby hospitals, pharmacies, mosques, ATMs, food, hotels."""
import httpx

from ..config import get_settings
from ..geo import haversine_km
from ..http import Fetched, fetch_json
from ..schemas import Place

URL = "https://overpass-api.de/api/interpreter"
KINDS = {
    "hospital": '["amenity"~"hospital|clinic"]',
    "pharmacy": '["amenity"="pharmacy"]',
    "mosque": '["amenity"="place_of_worship"]["religion"="muslim"]',
    "atm": '["amenity"="atm"]',
    "restaurant": '["amenity"="restaurant"]',
    "hotel": '["tourism"~"hotel|guest_house|resort"]',
}


async def find_nearby(client: httpx.AsyncClient, lat: float, lon: float, kind: str = "hospital",
                      radius_m: int = 10000, limit: int = 15) -> Fetched:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    q = f"[out:json][timeout:20];nwr{KINDS[kind]}(around:{radius_m},{lat},{lon});out center {limit};"
    return await fetch_json(client, URL, {"data": q}, ttl=get_settings().ttl_static)


def parse_places(fetched: Fetched, lat: float, lon: float, limit: int = 5) -> list[Place]:
    places: list[Place] = []
    for el in (fetched.data or {}).get("elements", []):
        c = el.get("center") or el
        if "lat" not in c or "lon" not in c:
            continue
        name = (el.get("tags") or {}).get("name") or (el.get("tags") or {}).get("name:en") or "(unnamed)"
        places.append(Place(name=name[:80], lat=c["lat"], lon=c["lon"],
                            distance_km=round(haversine_km(lat, lon, c["lat"], c["lon"]), 1)))
    return sorted(places, key=lambda p: p.distance_km)[:limit]
