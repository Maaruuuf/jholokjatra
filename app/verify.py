"""Hallucination check: every number in a generated narrative must be traceable to evidence."""
from __future__ import annotations

import re

from .parser import BN_DIGITS
from .schemas import DayVerdict

_NUM = re.compile(r"\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(text.translate(BN_DIGITS))]


def allowed_numbers(days: list[DayVerdict], extra: list[float] | None = None) -> set[float]:
    allowed: set[float] = set(extra or [])
    for d in days:
        allowed.update({float(d.day.year), float(d.day.month), float(d.day.day), float(d.score)})
        allowed.update(d.metrics.values())
        for r in d.reasons:
            for v in (r.value, r.threshold):
                if v is not None:
                    allowed.add(v)
            allowed.update(numbers_in(r.message))
    return allowed


def unsupported_numbers(text: str, allowed: set[float]) -> list[float]:
    bad = []
    for n in numbers_in(text):
        if not any(abs(n - a) <= max(0.051, 0.01 * abs(a)) for a in allowed):
            bad.append(n)
    return bad
