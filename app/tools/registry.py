"""Tool registry: Pydantic-validated arguments, JSON schemas for LLM function calling, and
error results the model can read and recover from (never raw exceptions)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from ..clients import gdacs, open_meteo, overpass
from ..context import AppContext
from ..data import gather_data
from ..destinations import Destination, resolve, valid_keys
from ..http import UpstreamError
from ..memory.prefs import load_prefs
from ..scoring import assess_all, scales_from

BD_TZ = dt.timezone(dt.timedelta(hours=6))


def today_dhaka() -> dt.date:
    return dt.datetime.now(BD_TZ).date()


class ToolError(Exception):
    pass


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error: Optional[str] = None


class DestArgs(BaseModel):
    destination: str = Field(..., description="Destination name or key, e.g. 'sajek' or 'Cox's Bazar'")


class ForecastArgs(DestArgs):
    days: int = Field(5, ge=1, le=16)


class NearbyArgs(DestArgs):
    kind: Literal["hospital", "pharmacy", "mosque", "atm", "restaurant", "hotel"] = "hospital"
    radius_km: float = Field(10, gt=0, le=30)


class AlertArgs(DestArgs):
    pass


class AssessArgs(DestArgs):
    start_date: Optional[dt.date] = None
    end_date: Optional[dt.date] = None


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[AppContext, Any], Awaitable[dict]]


def _dest(name: str) -> Destination:
    d = resolve(name)
    if not d:
        raise ToolError(f"Unknown destination '{name}'. Valid destinations: {', '.join(valid_keys())}")
    return d


def _at(daily: dict, key: str, i: int):
    series = daily.get(key) or []
    return series[i] if i < len(series) else None


async def _forecast(ctx: AppContext, a: ForecastArgs) -> dict:
    d = _dest(a.destination)
    f = await open_meteo.get_forecast(ctx.http, d.lat, d.lon, 16)
    daily = f.data.get("daily", {})
    rows = []
    for i, day in enumerate((daily.get("time") or [])[: a.days]):
        rows.append({"date": day, "rain_mm": _at(daily, "precipitation_sum", i),
                     "rain_prob_pct": _at(daily, "precipitation_probability_max", i),
                     "gust_kmh": _at(daily, "wind_gusts_10m_max", i), "tmax_c": _at(daily, "temperature_2m_max", i)})
    return {"destination": d.name, "evidence_ref": f.ref, "days": rows}


async def _marine(ctx: AppContext, a: DestArgs) -> dict:
    d = _dest(a.destination)
    if not d.sea_point:
        raise ToolError(f"{d.name} is not a sea destination; no wave data.")
    f = await open_meteo.get_marine(ctx.http, *d.sea_point, days=7)
    daily = f.data.get("daily", {})
    return {"destination": d.name, "evidence_ref": f.ref,
            "days": [{"date": t, "wave_max_m": w} for t, w in zip(daily.get("time", []), daily.get("wave_height_max", []))]}


async def _flood(ctx: AppContext, a: DestArgs) -> dict:
    d = _dest(a.destination)
    f = await open_meteo.get_flood(ctx.http, d.lat, d.lon, 10)
    daily = f.data.get("daily", {})
    return {"destination": d.name, "evidence_ref": f.ref,
            "days": [{"date": t, "river_discharge_m3s": v} for t, v in zip(daily.get("time", []), daily.get("river_discharge", []))]}


async def _nearby(ctx: AppContext, a: NearbyArgs) -> dict:
    d = _dest(a.destination)
    f = await overpass.find_nearby(ctx.http, d.lat, d.lon, a.kind, int(a.radius_km * 1000))
    return {"destination": d.name, "evidence_ref": f.ref,
            "places": [p.model_dump() for p in overpass.parse_places(f, d.lat, d.lon)]}


async def _alerts(ctx: AppContext, a: AlertArgs) -> dict:
    d = _dest(a.destination)
    today = today_dhaka()
    f = await gdacs.get_events(ctx.http, today - dt.timedelta(days=14), today + dt.timedelta(days=1))
    alerts = gdacs.parse_events(f, d.lat, d.lon)
    return {"destination": d.name, "evidence_ref": f.ref,
            "alerts": [{"kind": x.kind, "name": x.name, "level": x.level, "distance_km": x.distance_km,
                        "from": str(x.start), "to": str(x.end)} for x in alerts]}


async def _assess(ctx: AppContext, a: AssessArgs) -> dict:
    d = _dest(a.destination)
    today = today_dhaka()
    start = max(a.start_date or today, today)
    end = min(a.end_date or start + dt.timedelta(days=6), today + dt.timedelta(days=15))
    if start > end:
        raise ToolError("Date range is outside the 16-day forecast window.")
    bundle = await gather_data(ctx.http, d, start, end, today)
    days = [start + dt.timedelta(n) for n in range((end - start).days + 1)]
    verdicts = assess_all(days, bundle, scales_from(load_prefs("default")))
    return {"destination": d.name, "gaps": bundle.gaps,
            "days": [{"date": str(v.day), "verdict": v.verdict.value, "score": v.score,
                      "reasons": [{"msg": r.message, "evidence_ref": r.ref} for r in v.reasons]} for v in verdicts]}


TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("get_forecast", "Daily weather forecast (rain, gusts, max temp) for a destination.", ForecastArgs, _forecast),
    ToolSpec("get_marine", "Wave height forecast (next ~7 days) for coastal/island destinations.", DestArgs, _marine),
    ToolSpec("get_flood_risk", "River discharge forecast near a destination (GloFAS).", DestArgs, _flood),
    ToolSpec("get_alerts", "Active GDACS cyclone/flood alerts near a destination.", AlertArgs, _alerts),
    ToolSpec("find_nearby", "Nearby hospitals, pharmacies, mosques, ATMs, restaurants or hotels (OpenStreetMap).", NearbyArgs, _nearby),
    ToolSpec("assess_days", "Go/caution/avoid verdict per day with cited reasons. Best tool for 'when should I go'.", AssessArgs, _assess),
]}


def tool_schemas() -> list[dict]:
    """OpenAI/Groq-style function schemas, generated from the Pydantic models (dynamic discovery)."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.args_model.model_json_schema()}} for t in TOOLS.values()]


async def call_tool(ctx: AppContext, name: str, raw_args: dict | None) -> ToolResult:
    spec = TOOLS.get(name)
    if not spec:
        return ToolResult(ok=False, error=f"Unknown tool '{name}'. Available: {', '.join(TOOLS)}")
    try:
        args = spec.args_model.model_validate(raw_args or {})
    except ValidationError as exc:
        msgs = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return ToolResult(ok=False, error=f"Invalid arguments for {name}: {msgs}")
    try:
        return ToolResult(ok=True, data=await spec.handler(ctx, args))
    except (ToolError, UpstreamError, ValueError) as exc:
        return ToolResult(ok=False, error=str(exc)[:300])
