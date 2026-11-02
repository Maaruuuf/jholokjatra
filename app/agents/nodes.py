"""Agent nodes. Each returns a partial state update. Specialists are deterministic and cited; the LLM is only
used by the narrator, and only ever sees structured evidence (never scraped text)."""
from __future__ import annotations

import datetime as dt
import json
import logging

from ..clients import overpass
from ..context import AppContext
from ..destinations import Destination
from ..llm.budget import BudgetExceeded
from ..llm.router import LLMUnavailable
from ..memory import tips as tips_mem
from ..schemas import DayVerdict, Verdict
from ..scoring import assess_group, merge_day
from ..tracing import span
from ..verify import allowed_numbers, unsupported_numbers

log = logging.getLogger("jholokjatra.agents")


def weather_agent(state: dict) -> dict:
    with span("agent.weather"):
        return {"opinions": [{"agent": "weather", "days": {
            d.isoformat(): assess_group(d, state["bundle"], state["scales"], "weather") for d in state["days"]}}]}


def safety_agent(state: dict) -> dict:
    with span("agent.safety"):
        return {"opinions": [{"agent": "safety", "days": {
            d.isoformat(): assess_group(d, state["bundle"], state["scales"], "safety") for d in state["days"]}}]}


async def logistics_agent(state: dict) -> dict:
    ctx: AppContext = state["ctx"]
    dest: Destination = state["dest"]
    with span("agent.logistics"):
        try:
            f = await overpass.find_nearby(ctx.http, dest.lat, dest.lon, "hospital", 20000)
            return {"hospitals": overpass.parse_places(f, dest.lat, dest.lon, 3)}
        except Exception as exc:  # optional enrichment: never fail the plan
            return {"hospitals": [], "notes": [f"nearby hospitals unavailable ({type(exc).__name__})"]}


async def guide_agent(state: dict) -> dict:
    ctx: AppContext = state["ctx"]
    dest: Destination = state["dest"]
    with span("agent.guide"):
        try:
            await tips_mem.ensure_indexed(ctx.http, dest)
            return {"tips": tips_mem.search(dest.key, "how to get there safety weather best season tips", 3)}
        except Exception as exc:
            return {"tips": [], "notes": [f"travel tips unavailable ({type(exc).__name__})"]}


def supervisor(state: dict) -> dict:
    """Merge specialist opinions. Safety has veto power: the final verdict is the worst of all agents."""
    with span("agent.supervisor"):
        by_agent = {o["agent"]: o["days"] for o in state["opinions"]}
        final: list[DayVerdict] = []
        conflicts: list[str] = []
        for d in state["days"]:
            k = d.isoformat()
            per = {a: days[k] for a, days in by_agent.items()}
            v = merge_day(d, state["bundle"], per)
            final.append(v)
            w, s = v.agents.get("weather", Verdict.GO), v.agents.get("safety", Verdict.GO)
            if w == Verdict.GO and s != Verdict.GO and len(conflicts) < 5:
                top = next((r for r in v.reasons if r.metric.startswith(("gdacs", "wave", "flood", "earthq"))), None)
                conflicts.append(f"{k}: weather says go, safety says {s.value} ({top.message if top else 'see reasons'}). "
                                 "Safety veto applied.")
        return {"final": final, "conflicts": conflicts}


def template_narrative(dest: Destination, days: list[DayVerdict], best: list[dt.date], best_is_caution: bool,
                       lang: str = "en") -> str:
    avoid = [d for d in days if d.verdict == Verdict.AVOID]
    name = dest.name_bn if lang == "bn" else dest.name
    if best:
        label = "least-risky (caution)" if best_is_caution else "best"
        text = f"{name}: {label} days are {', '.join(d.isoformat() for d in best)}."
    else:
        text = f"{name}: no day in this range looks safe to recommend."
    if avoid:
        top = avoid[0].reasons[0].message if avoid[0].reasons else ""
        text += f" Avoid {', '.join(d.day.isoformat() for d in avoid[:4])}. Main reason on {avoid[0].day.isoformat()}: {top}"
    return text


async def narrator(state: dict) -> dict:
    ctx: AppContext = state["ctx"]
    dest: Destination = state["dest"]
    days: list[DayVerdict] = state["final"]
    best, best_caution = state["best"], state["best_is_caution"]
    fallback = template_narrative(dest, days, best, best_caution, state["lang"])
    with span("agent.narrator") as attrs:
        evidence = [{"date": d.day.isoformat(), "verdict": d.verdict.value, "score": d.score,
                     "reasons": [r.message for r in d.reasons]} for d in days]
        lang = "Bangla (keep numbers as digits)" if state["lang"] == "bn" else "English"
        msgs = [
            {"role": "system", "content": (
                f"You are JholokJatra, a careful travel advisor for Bangladesh. Write in {lang}, max 120 words. "
                "Use ONLY the facts in EVIDENCE. Every number you write must appear in EVIDENCE. Never invent weather, "
                "prices or places. Say which days to go, which to avoid and the main reason. If safety data is missing, say so.")},
            {"role": "user", "content": f"Destination: {dest.name}\nBest days: {[d.isoformat() for d in best]}\n"
                                         f"EVIDENCE: {json.dumps(evidence, ensure_ascii=False)}"},
        ]
        extra = [float(len(days)), float(len(best)), float(sum(d.verdict == Verdict.AVOID for d in days)),
                 float(sum(d.verdict == Verdict.CAUTION for d in days)), float(sum(d.verdict == Verdict.GO for d in days))]
        allowed = allowed_numbers(days, extra)
        try:
            for _attempt in range(2):
                res = await ctx.llm.complete(msgs, tier="large", max_tokens=350, temperature=0.2,
                                             budget=state["budget"], purpose="narrate")
                bad = unsupported_numbers(res.text, allowed)
                if not bad:
                    attrs["source"] = f"{res.provider}/{res.model}"
                    return {"narrative": res.text.strip(), "narrative_source": f"llm:{res.provider}/{res.model}"}
                msgs = msgs + [{"role": "assistant", "content": res.text},
                               {"role": "user", "content": f"These numbers are not in EVIDENCE: {bad}. Rewrite using only EVIDENCE numbers."}]
            return {"narrative": fallback, "narrative_source": "template (llm numbers failed verification)"}
        except (LLMUnavailable, BudgetExceeded) as exc:
            return {"narrative": fallback, "narrative_source": f"template ({type(exc).__name__})"}
