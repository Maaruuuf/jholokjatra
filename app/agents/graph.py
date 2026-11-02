"""Multi-agent orchestration with LangGraph (falls back to plain asyncio if langgraph is missing).

START -> [weather | safety | logistics | guide]  (parallel)  -> supervisor -> narrator -> END
"""
from __future__ import annotations

import asyncio
import operator
from typing import Annotated, Any, TypedDict

from ..scoring import pick_best
from . import nodes


class PlanState(TypedDict, total=False):
    ctx: Any
    dest: Any
    days: list
    bundle: Any
    scales: Any
    lang: str
    budget: Any
    opinions: Annotated[list, operator.add]
    notes: Annotated[list, operator.add]
    hospitals: list
    tips: list
    final: list
    conflicts: list
    best: list
    best_is_caution: bool
    narrative: str
    narrative_source: str


async def _supervise_and_pick(state: dict) -> dict:
    out = nodes.supervisor(state)
    best, caution = pick_best(out["final"])
    return {**out, "best": best, "best_is_caution": caution}


def _build_graph():
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PlanState)
    g.add_node("weather", nodes.weather_agent)
    g.add_node("safety", nodes.safety_agent)
    g.add_node("logistics", nodes.logistics_agent)
    g.add_node("guide", nodes.guide_agent)
    g.add_node("supervisor", _supervise_and_pick)
    g.add_node("narrator", nodes.narrator)
    for n in ("weather", "safety", "logistics", "guide"):
        g.add_edge(START, n)
    g.add_edge(["weather", "safety", "logistics", "guide"], "supervisor")
    g.add_edge("supervisor", "narrator")
    g.add_edge("narrator", END)
    return g.compile()


_compiled = None


async def run_agents(state: dict) -> dict:
    global _compiled
    state = {**state, "opinions": [], "notes": []}
    try:
        if _compiled is None:
            _compiled = _build_graph()
        return await _compiled.ainvoke(state)
    except ImportError:
        pass  # langgraph not installed: identical behaviour, sequential orchestration
    parts = await asyncio.gather(
        asyncio.to_thread(nodes.weather_agent, state), asyncio.to_thread(nodes.safety_agent, state),
        nodes.logistics_agent(state), nodes.guide_agent(state))
    merged = dict(state)
    for p in parts:
        for k, v in p.items():
            merged[k] = merged.get(k, []) + v if k in ("opinions", "notes") else v
    merged.update(await _supervise_and_pick(merged))
    merged.update(await nodes.narrator(merged))
    return merged
