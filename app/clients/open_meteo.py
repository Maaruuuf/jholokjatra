"""Open-Meteo: forecast, marine waves, GloFAS flood discharge, and historical archive (all free, no key)."""
import datetime as dt

import httpx

from ..config import get_settings
from ..http import Fetched, fetch_json

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
TZ = "Asia/Dhaka"

DAILY_COMMON = ["weather_code", "temperature_2m_max", "precipitation_sum", "wind_gusts_10m_max"]
DAILY_FORECAST = DAILY_COMMON + ["precipitation_probability_max", "temperature_2m_min", "wind_speed_10m_max"]
DAILY_MARINE = ["wave_height_max", "wave_period_max", "wind_wave_height_max"]
DAILY_FLOOD = ["river_discharge", "river_discharge_max"]


async def get_forecast(client: httpx.AsyncClient, lat: float, lon: float, days: int = 16) -> Fetched:
    return await fetch_json(client, FORECAST_URL, {
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY_FORECAST),
        "forecast_days": days, "timezone": TZ}, ttl=get_settings().ttl_forecast)


async def get_marine(client: httpx.AsyncClient, lat: float, lon: float, days: int = 7) -> Fetched:
    return await fetch_json(client, MARINE_URL, {
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY_MARINE),
        "forecast_days": days, "timezone": TZ}, ttl=get_settings().ttl_forecast)


async def get_flood(client: httpx.AsyncClient, lat: float, lon: float, days: int = 16) -> Fetched:
    return await fetch_json(client, FLOOD_URL, {
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY_FLOOD),
        "forecast_days": days}, ttl=get_settings().ttl_forecast)


# ---- historical (used by the backtest) ----
async def get_history(client, lat, lon, start: dt.date, end: dt.date) -> Fetched:
    return await fetch_json(client, ARCHIVE_URL, {
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY_COMMON),
        "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": TZ},
        ttl=get_settings().ttl_static)


async def get_marine_history(client, lat, lon, start: dt.date, end: dt.date) -> Fetched:
    return await fetch_json(client, MARINE_URL, {
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY_MARINE),
        "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": TZ},
        ttl=get_settings().ttl_static)


async def get_flood_history(client, lat, lon, start: dt.date, end: dt.date) -> Fetched:
    return await fetch_json(client, FLOOD_URL, {
        "latitude": lat, "longitude": lon, "daily": ",".join(DAILY_FLOOD),
        "start_date": start.isoformat(), "end_date": end.isoformat()}, ttl=get_settings().ttl_static)
