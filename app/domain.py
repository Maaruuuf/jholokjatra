"""Plain dataclasses for fetched data. No I/O here, so scoring stays pure and testable."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Metric:
    value: float
    source: str
    url: str
    ref: str


@dataclass
class Alert:  # GDACS event
    kind: str  # TC (tropical cyclone) | FL (flood)
    name: str
    level: str  # Green | Orange | Red
    lat: float
    lon: float
    start: dt.date
    end: dt.date
    distance_km: float
    url: str
    ref: str


@dataclass
class Quake:  # USGS event
    mag: float
    place: str
    day: dt.date
    distance_km: float
    url: str
    ref: str


@dataclass
class DataBundle:
    dest_key: str
    metrics: dict[str, dict[str, Metric]] = field(default_factory=dict)  # ISO date -> metric name -> Metric
    alerts: list[Alert] = field(default_factory=list)
    quakes: list[Quake] = field(default_factory=list)
    sea_trip: bool = False
    marine_ref: str = ""
    marine_url: str = ""
    gaps: list[str] = field(default_factory=list)
    refs: dict[str, str] = field(default_factory=dict)
