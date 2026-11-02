"""Fetch everything for a plan in parallel and normalise it into a DataBundle."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging

import httpx

from .clients import gdacs, open_meteo, usgs
from .destinations import Destination
from .domain import DataBundle
from .http import Fetched, UpstreamError
from .scoring import daily_metrics, flood_metrics, merge_metrics

log = logging.getLogger("jholokjatra.data")


def _ingest(bundle: DataBundle, name: str, res, dest: Destination) -> list[dict]:
    """Turn one fetch result (or exception) into metrics/alerts. Returns metric dicts to merge."""
    if isinstance(res, BaseException):
        bundle.gaps.append(f"{name} unavailable ({type(res).__name__}: {str(res)[:120]})")
        return []
    f: Fetched = res
    bundle.refs[name] = f.ref
    if f.stale:
        bundle.gaps.append(f"{name} served from stale cache")
    if name in ("forecast", "history"):
        return [daily_metrics(f.data, "Open-Meteo Forecast" if name == "forecast" else "Open-Meteo Archive", f.url, f.ref)]
    if name in ("marine", "marine_history"):
        bundle.marine_ref, bundle.marine_url = f.ref, f.url
        return [daily_metrics(f.data, "Open-Meteo Marine", f.url, f.ref)]
    if name in ("flood", "flood_history"):
        return [flood_metrics(f.data, f.url, f.ref)]
    if name == "gdacs":
        bundle.alerts = gdacs.parse_events(f, dest.lat, dest.lon)
    elif name == "usgs":
        bundle.quakes = usgs.parse_quakes(f, dest.lat, dest.lon)
    return []


async def _run(jobs: dict, dest: Destination, bundle: DataBundle) -> None:
    results = await asyncio.gather(*jobs.values(), return_exceptions=True)
    parts: list[dict] = []
    for name, res in zip(jobs, results):
        parts += _ingest(bundle, name, res, dest)
    bundle.metrics = merge_metrics(*parts)


async def gather_data(client: httpx.AsyncClient, dest: Destination, start: dt.date, end: dt.date,
                      today: dt.date) -> DataBundle:
    """Live forecast data. Raises UpstreamError only if the core forecast is missing."""
    bundle = DataBundle(dest_key=dest.key, sea_trip=dest.sea_point is not None)
    jobs = {"forecast": open_meteo.get_forecast(client, dest.lat, dest.lon, 16)}
    if dest.sea_point:
        jobs["marine"] = open_meteo.get_marine(client, *dest.sea_point, days=7)
    if dest.flood:
        jobs["flood"] = open_meteo.get_flood(client, dest.lat, dest.lon, 16)
    jobs["gdacs"] = gdacs.get_events(client, today - dt.timedelta(days=14), end + dt.timedelta(days=1))
    jobs["usgs"] = usgs.get_quakes(client, dest.lat, dest.lon, today - dt.timedelta(days=3))
    await _run(jobs, dest, bundle)
    if not bundle.refs.get("forecast"):
        raise UpstreamError("Weather forecast unavailable; cannot plan without it.")
    return bundle


async def gather_historical(client: httpx.AsyncClient, dest: Destination, start: dt.date, end: dt.date) -> DataBundle:
    """Observed/reanalysis data for backtests. Window is padded so flood ratios have context."""
    bundle = DataBundle(dest_key=dest.key, sea_trip=dest.sea_point is not None)
    pad_start, pad_end = start - dt.timedelta(days=7), end + dt.timedelta(days=3)
    jobs = {"history": open_meteo.get_history(client, dest.lat, dest.lon, pad_start, pad_end)}
    if dest.sea_point:
        jobs["marine_history"] = open_meteo.get_marine_history(client, *dest.sea_point, pad_start, pad_end)
    if dest.flood:
        jobs["flood_history"] = open_meteo.get_flood_history(client, dest.lat, dest.lon, pad_start, pad_end)
    jobs["gdacs"] = gdacs.get_events(client, pad_start - dt.timedelta(days=10), pad_end, ttl=7 * 86400)
    await _run(jobs, dest, bundle)
    return bundle
