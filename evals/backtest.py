"""Backtest the scoring engine against past events using Open-Meteo archive/marine/flood history + GDACS.

Run:  python -m evals.backtest            (needs internet; writes evals/reports/backtest.md)
Exit code 1 if the hit rate is below --min-hit-rate (usable as a CI gate).

Caveat: this scores *observed* conditions, which tests the thresholds and rule logic. It does not test
forecast skill (what was predicted days earlier). Treat results as sanity checks on the rules.
"""
import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

import httpx

from app.config import get_settings
from app.data import gather_historical
from app.destinations import DESTINATIONS
from app.scoring import Scales, assess_all

RANK = {"go": 0, "caution": 1, "avoid": 2}
FIXTURES = Path(__file__).parent / "fixtures" / "events.json"
REPORT = Path(__file__).parent / "reports" / "backtest.md"


async def run(min_hit_rate: float) -> int:
    events = json.loads(FIXTURES.read_text(encoding="utf-8"))["events"]
    s = get_settings()
    rows, hits, total = [], 0, 0
    async with httpx.AsyncClient(headers={"User-Agent": s.http_user_agent}, follow_redirects=True) as client:
        for ev in events:
            dest = DESTINATIONS[ev["destination"]]
            start, end = dt.date.fromisoformat(ev["start"]), dt.date.fromisoformat(ev["end"])
            try:
                bundle = await gather_historical(client, dest, start, end)
            except Exception as exc:  # noqa: BLE001
                rows.append(f"| {ev['id']} | - | ERROR {type(exc).__name__}: {exc} | skipped |")
                continue
            days = [start + dt.timedelta(n) for n in range((end - start).days + 1)]
            verdicts = assess_all(days, bundle, Scales())
            for v in verdicts:
                total += 1
                ok = (RANK[v.verdict.value] >= RANK[ev["min_verdict"]]) if "min_verdict" in ev \
                    else (RANK[v.verdict.value] <= RANK[ev["max_verdict"]])
                hits += ok
                why = "; ".join(r.message for r in v.reasons[:2]) or "no rule triggered"
                rows.append(f"| {ev['id']} | {v.day} | {v.verdict.value} (score {v.score}) | {'PASS' if ok else 'FAIL'} | {why} |")
            if bundle.gaps:
                rows.append(f"| {ev['id']} | - | data gaps: {'; '.join(bundle.gaps)} | note | |")
    rate = hits / total if total else 0.0
    out = ["# Backtest report", f"\nGenerated {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}",
           f"\n**Hit rate: {hits}/{total} = {rate:.0%}**\n",
           "| event | day | verdict | result | evidence |", "|---|---|---|---|---|", *rows]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    return 0 if rate >= min_hit_rate else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hit-rate", type=float, default=0.0)
    sys.exit(asyncio.run(run(ap.parse_args().min_hit_rate)))
