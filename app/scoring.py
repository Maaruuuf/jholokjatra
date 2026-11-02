"""Deterministic, evidence-producing scoring. No LLM involved: every verdict is auditable.

Thresholds are conservative heuristics for travel comfort/safety, NOT official warnings.
Always defer to the Bangladesh Meteorological Department / local authorities for storm signals.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .domain import Alert, DataBundle, Metric, Quake
from .schemas import DayVerdict, Evidence, Preferences, Verdict

INF = float("inf")
_RANK = {Verdict.GO: 0, Verdict.CAUTION: 1, Verdict.AVOID: 2}
_PENALTY = {Verdict.CAUTION: 15, Verdict.AVOID: 40}
THUNDER_CODES = {95, 96, 99}


@dataclass(frozen=True)
class Rule:
    metric: str
    label: str
    unit: str
    caution: float
    avoid: float
    group: str  # "weather" | "safety"
    sea_only: bool = False


RULES: tuple[Rule, ...] = (
    Rule("precipitation_sum", "Rainfall", "mm", 20, 60, "weather"),
    Rule("precipitation_probability_max", "Rain probability", "%", 80, INF, "weather"),
    Rule("wind_gusts_10m_max", "Wind gusts", "km/h", 45, 70, "weather"),
    Rule("temperature_2m_max", "Max temperature", "°C", 36, 40, "weather"),
    Rule("wave_height_max", "Wave height", "m", 1.5, 2.5, "safety", sea_only=True),
    Rule("flood_ratio", "River discharge vs. window minimum", "x", 1.5, 2.5, "safety"),
)


@dataclass(frozen=True)
class Scales:
    """Threshold adjustments from user preferences. <1 means stricter."""
    mult: float = 1.0
    wave_mult: float = 1.0
    temp_offset: float = 0.0


def scales_from(p: Preferences) -> Scales:
    mult = {"low": 0.8, "medium": 1.0, "high": 1.2}[p.risk_tolerance]
    if p.traveling_with_kids or p.elderly_travelers:
        mult *= 0.85
    return Scales(mult=mult, wave_mult=0.7 if p.motion_sickness else 1.0,
                  temp_offset=-2.0 if (p.traveling_with_kids or p.elderly_travelers) else 0.0)


def _thresholds(rule: Rule, sc: Scales) -> tuple[float, float]:
    if rule.metric == "temperature_2m_max":
        return rule.caution + sc.temp_offset, rule.avoid + sc.temp_offset
    if rule.metric == "precipitation_probability_max":
        return rule.caution, rule.avoid
    m = sc.mult * (sc.wave_mult if rule.metric == "wave_height_max" else 1.0)
    return rule.caution * m, rule.avoid * m


# ---------- metric extraction from API payloads ----------
def daily_metrics(data: dict, source: str, url: str, ref: str) -> dict[str, dict[str, Metric]]:
    daily = (data or {}).get("daily") or {}
    times = daily.get("time") or []
    out: dict[str, dict[str, Metric]] = {t: {} for t in times}
    for var, series in daily.items():
        if var == "time" or not isinstance(series, list):
            continue
        for t, v in zip(times, series):
            if v is None:
                continue
            try:
                out[t][var] = Metric(float(v), source, url, ref)
            except (TypeError, ValueError):
                continue
    return out


def flood_metrics(data: dict, url: str, ref: str) -> dict[str, dict[str, Metric]]:
    """Heuristic: discharge relative to the lowest value in the window. Rising rivers score high."""
    daily = (data or {}).get("daily") or {}
    times, series = daily.get("time") or [], daily.get("river_discharge") or []
    positive = [v for v in series if isinstance(v, (int, float)) and v > 0]
    if len(positive) < 3:
        return {}
    base = min(positive)
    out: dict[str, dict[str, Metric]] = {}
    for t, v in zip(times, series):
        if isinstance(v, (int, float)) and v > 0:
            out[t] = {"flood_ratio": Metric(round(v / base, 2), "Open-Meteo Flood (GloFAS)", url, ref)}
    return out


def merge_metrics(*parts: dict[str, dict[str, Metric]]) -> dict[str, dict[str, Metric]]:
    merged: dict[str, dict[str, Metric]] = {}
    for part in parts:
        for day, ms in part.items():
            merged.setdefault(day, {}).update(ms)
    return merged


# ---------- per-group assessment ----------
def _alert_verdict(a: Alert) -> Verdict | None:
    if a.kind == "TC":
        if a.distance_km > 800:
            return None
        if a.level in ("Orange", "Red"):
            return Verdict.AVOID
        return Verdict.CAUTION if a.distance_km <= 500 else None
    if a.kind == "FL" and a.distance_km <= 300:
        return Verdict.AVOID if a.level == "Red" else Verdict.CAUTION if a.level == "Orange" else None
    return None


def _quake_verdict(q: Quake) -> Verdict | None:
    if q.distance_km > 300:
        return None
    return Verdict.AVOID if q.mag >= 7 else Verdict.CAUTION if q.mag >= 5.5 else None


def worst(reasons: list[Evidence]) -> Verdict:
    return max((r.verdict for r in reasons), key=_RANK.get, default=Verdict.GO)


def score_from(reasons: list[Evidence]) -> int:
    return max(0, 100 - sum(_PENALTY[r.verdict] for r in reasons))


def assess_group(day: dt.date, bundle: DataBundle, scales: Scales, group: str) -> list[Evidence]:
    key = day.isoformat()
    m = bundle.metrics.get(key, {})
    reasons: list[Evidence] = []

    for rule in RULES:
        if rule.group != group or (rule.sea_only and not bundle.sea_trip):
            continue
        met = m.get(rule.metric)
        if met is None:
            if rule.sea_only:
                reasons.append(Evidence(
                    source="Open-Meteo Marine", metric=rule.metric, label="Wave forecast unavailable",
                    verdict=Verdict.CAUTION, url=bundle.marine_url, ref=bundle.marine_ref,
                    message="No marine forecast for this date (marine data covers about 7 days); sea conditions unknown."))
            continue
        caution, avoid = _thresholds(rule, scales)
        if met.value >= avoid:
            v, thr = Verdict.AVOID, avoid
        elif met.value >= caution:
            v, thr = Verdict.CAUTION, caution
        else:
            continue
        reasons.append(Evidence(
            source=met.source, metric=rule.metric, label=rule.label, verdict=v, value=round(met.value, 2),
            unit=rule.unit, threshold=round(thr, 2), url=met.url, ref=met.ref,
            message=f"{rule.label} {met.value:g} {rule.unit} is at or above the {v.value} threshold of {thr:g} {rule.unit}."))

    if group == "weather":
        code = m.get("weather_code")
        if code and int(code.value) in THUNDER_CODES:
            reasons.append(Evidence(source=code.source, metric="weather_code", label="Thunderstorm",
                                    verdict=Verdict.CAUTION, value=code.value, url=code.url, ref=code.ref,
                                    message=f"Thunderstorm forecast (WMO weather code {int(code.value)})."))

    if group == "safety":
        for a in bundle.alerts:
            v = _alert_verdict(a)
            if v and a.start - dt.timedelta(days=1) <= day <= a.end + dt.timedelta(days=1):
                kind = "tropical cyclone" if a.kind == "TC" else "flood"
                reasons.append(Evidence(
                    source="GDACS", metric=f"gdacs_{a.kind.lower()}", label=f"{a.level} {kind} alert", verdict=v,
                    value=a.distance_km, unit="km", url=a.url, ref=a.ref,
                    message=f"GDACS {a.level} {kind} alert '{a.name}', {a.distance_km:g} km away, active {a.start} to {a.end}."))
        for q in bundle.quakes:
            v = _quake_verdict(q)
            if v and q.day <= day <= q.day + dt.timedelta(days=2):
                reasons.append(Evidence(
                    source="USGS", metric="earthquake", label="Recent earthquake", verdict=v, value=q.mag,
                    unit="M", url=q.url, ref=q.ref,
                    message=f"Magnitude {q.mag:g} earthquake {q.distance_km:g} km away on {q.day} ({q.place})."))
    return reasons


def merge_day(day: dt.date, bundle: DataBundle, per_agent: dict[str, list[Evidence]]) -> DayVerdict:
    reasons = sorted((r for rs in per_agent.values() for r in rs), key=lambda r: -_RANK[r.verdict])
    snap = {k: round(v.value, 2) for k, v in bundle.metrics.get(day.isoformat(), {}).items()}
    return DayVerdict(day=day, verdict=worst(reasons), score=score_from(reasons), reasons=reasons,
                      metrics=snap, agents={a: worst(rs) for a, rs in per_agent.items()})


def assess_all(days: list[dt.date], bundle: DataBundle, scales: Scales) -> list[DayVerdict]:
    """Convenience for tools/backtests: weather + safety merged, no agents/LLM."""
    return [merge_day(d, bundle, {"weather": assess_group(d, bundle, scales, "weather"),
                                  "safety": assess_group(d, bundle, scales, "safety")}) for d in days]


def pick_best(days: list[DayVerdict], k: int = 3) -> tuple[list[dt.date], bool]:
    go = sorted((d for d in days if d.verdict == Verdict.GO), key=lambda d: (-d.score, d.day))[:k]
    if go:
        return sorted(d.day for d in go), False
    ok = sorted((d for d in days if d.verdict == Verdict.CAUTION), key=lambda d: (-d.score, d.day))[:k]
    return sorted(d.day for d in ok), bool(ok)
