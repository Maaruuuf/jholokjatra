"""Lightweight tracing: every span is stored in SQLite and summarised at GET /metrics.

(Stage 9 upgrade path: export the same spans to Arize Phoenix / Langfuse via OpenTelemetry.)
"""
import json
import logging
import time
from contextlib import contextmanager

from .db import db

log = logging.getLogger("jholokjatra.trace")


@contextmanager
def span(name: str, **attrs):
    t0 = time.perf_counter()
    ok = True
    try:
        yield attrs
    except Exception:
        ok = False
        raise
    finally:
        ms = (time.perf_counter() - t0) * 1000
        try:
            with db() as c:
                c.execute(
                    "INSERT INTO traces(ts,name,duration_ms,ok,attrs) VALUES (?,?,?,?,?)",
                    (time.time(), name, ms, int(ok), json.dumps(attrs, default=str)[:2000]),
                )
        except Exception:  # tracing must never break the request
            log.exception("failed to record span %s", name)


def metrics_summary() -> dict:
    with db() as c:
        spans = [
            dict(r)
            for r in c.execute(
                "SELECT name, COUNT(*) n, ROUND(AVG(duration_ms),1) avg_ms, ROUND(MAX(duration_ms),1) max_ms, "
                "SUM(1-ok) errors FROM traces GROUP BY name ORDER BY n DESC"
            )
        ]
        llm = [
            dict(r)
            for r in c.execute(
                "SELECT provider, model, COUNT(*) calls, SUM(prompt_tokens) prompt_tokens, "
                "SUM(completion_tokens) completion_tokens, ROUND(AVG(latency_ms),0) avg_latency_ms, "
                "SUM(1-ok) failures FROM llm_usage GROUP BY provider, model"
            )
        ]
        plans = c.execute("SELECT status, COUNT(*) n FROM plans GROUP BY status").fetchall()
    return {"spans": spans, "llm": llm, "plans": {r["status"]: r["n"] for r in plans}, "cost_usd": 0.0}
