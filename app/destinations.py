"""Destination registry. Coordinates are approximate points of interest, not surveyed locations.

`sea_point` is an offshore grid point used for the marine (wave) API, because that API needs
an ocean cell and returns nothing for inland coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Destination:
    key: str
    name: str
    name_bn: str
    lat: float
    lon: float
    wikivoyage: str
    aliases: tuple[str, ...]
    sea_point: tuple[float, float] | None = None  # set => sea trip, fetch waves
    flood: bool = False  # fetch river discharge (GloFAS)


DESTINATIONS: dict[str, Destination] = {
    d.key: d
    for d in [
        Destination("coxs_bazar", "Cox's Bazar", "কক্সবাজার", 21.4272, 92.0058, "Cox's Bazar",
                    ("cox", "coxs bazar", "cox's bazar", "coxsbazar", "কক্সবাজার"), sea_point=(21.45, 91.90)),
        Destination("saint_martin", "Saint Martin's Island", "সেন্ট মার্টিন", 20.6276, 92.3225,
                    "Saint Martin's Island",
                    ("saint martin", "st martin", "st. martin", "saintmartin", "সেন্ট মার্টিন", "সেন্টমার্টিন",
                     "narikel jinjira"), sea_point=(20.58, 92.25)),
        Destination("kuakata", "Kuakata", "কুয়াকাটা", 21.8167, 90.1167, "Kuakata",
                    ("kuakata", "কুয়াকাটা"), sea_point=(21.70, 90.12)),
        Destination("sundarbans", "Sundarbans (Karamjal)", "সুন্দরবন", 22.27, 89.62, "Sundarbans",
                    ("sundarban", "sundarbans", "karamjal", "সুন্দরবন"), flood=True),
        Destination("ratargul", "Ratargul Swamp Forest", "রাতারগুল", 25.01, 91.93, "Ratargul Swamp Forest",
                    ("ratargul", "rata rgul", "রাতারগুল", "sylhet swamp"), flood=True),
        Destination("sajek", "Sajek Valley", "সাজেক", 23.3811, 92.2936, "Sajek Valley",
                    ("sajek", "সাজেক"), flood=False),
        Destination("bandarban", "Bandarban", "বান্দরবান", 22.1953, 92.2184, "Bandarban",
                    ("bandarban", "বান্দরবান", "nilgiri", "nafakhum"), flood=True),
        Destination("srimangal", "Sreemangal", "শ্রীমঙ্গল", 24.3065, 91.7296, "Sreemangal",
                    ("sreemangal", "srimangal", "শ্রীমঙ্গল", "tea garden"), flood=False),
    ]
}


def resolve(text: str | None) -> Destination | None:
    if not text:
        return None
    t = text.strip().lower()
    if t in DESTINATIONS:
        return DESTINATIONS[t]
    for d in DESTINATIONS.values():
        if t == d.name.lower() or t == d.name_bn:
            return d
    for d in DESTINATIONS.values():  # substring match, longest alias first to avoid "cox" shadowing
        for alias in sorted(d.aliases + (d.name.lower(),), key=len, reverse=True):
            if alias.lower() in t:
                return d
    return None


def valid_keys() -> list[str]:
    return sorted(DESTINATIONS)
