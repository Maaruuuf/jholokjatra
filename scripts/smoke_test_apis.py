"""Hit every public API once and report status/shape.  python -m scripts.smoke_test_apis
Run this first on your machine: it confirms the free APIs are reachable and their response shapes still match."""
import asyncio
import datetime as dt

import httpx

from app.clients import gdacs, open_meteo, overpass, usgs, wikivoyage
from app.config import get_settings
from app.destinations import DESTINATIONS

D = DESTINATIONS["coxs_bazar"]


async def check(name, coro, probe):
    try:
        r = await coro
        print(f"[OK] {name}: {probe(r)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[XX] {name}: {type(exc).__name__}: {str(exc)[:150]}")


async def main() -> None:
    s = get_settings()
    today = dt.date.today()
    async with httpx.AsyncClient(headers={"User-Agent": s.http_user_agent}, follow_redirects=True) as c:
        await check("Open-Meteo forecast", open_meteo.get_forecast(c, D.lat, D.lon, 16),
                    lambda f: f"{len(f.data['daily']['time'])} days, vars={list(f.data['daily'])[:4]}...")
        await check("Open-Meteo marine", open_meteo.get_marine(c, *D.sea_point, days=7),
                    lambda f: f"{len(f.data['daily']['time'])} days, waves={f.data['daily']['wave_height_max'][:3]}")
        await check("Open-Meteo flood", open_meteo.get_flood(c, D.lat, D.lon, 7),
                    lambda f: f"discharge={f.data['daily']['river_discharge'][:3]}")
        await check("GDACS", gdacs.get_events(c, today - dt.timedelta(days=30), today),
                    lambda f: f"keys={list(f.data)[:3]}, features={len(f.data.get('features', []))}")
        await check("USGS", usgs.get_quakes(c, D.lat, D.lon, today - dt.timedelta(days=30)),
                    lambda f: f"{len(f.data.get('features', []))} quakes M4.5+ within 300 km in 30 days")
        await check("Overpass", overpass.find_nearby(c, D.lat, D.lon, "hospital", 10000),
                    lambda f: f"{len(f.data.get('elements', []))} hospitals/clinics")
        await check("Wikivoyage", wikivoyage.get_extract(c, D.wikivoyage), lambda t: f"{len(t[0])} chars")


if __name__ == "__main__":
    asyncio.run(main())
