"""End-to-end plan: parse -> fetch (parallel) -> agents -> human-approval gate -> persist + audit trail."""
from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from typing import Awaitable, Callable, Optional

from .agents.graph import run_agents
from .context import AppContext
from .data import gather_data
from .db import db
from .destinations import resolve
from .http import UpstreamError
from .llm.budget import TokenBudget
from .memory.prefs import load_prefs
from .parser import ParseError, parse_request
from .schemas import PlanRequest, PlanResponse, Verdict
from .scoring import scales_from
from .tools.registry import today_dhaka
from .tracing import span

Progress = Callable[[str, str], Awaitable[None]]


class PlanError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


async def _noop(stage: str, detail: str = "") -> None:
    return None


def audit(plan_id: str | None, event: str, detail: dict | str = "") -> None:
    with db() as c:
        c.execute("INSERT INTO audit_log(ts,plan_id,event,detail) VALUES (?,?,?,?)",
                  (time.time(), plan_id, event, json.dumps(detail, default=str)[:4000]))


def _save(plan_id: str, status: str, req: PlanRequest, result: PlanResponse) -> None:
    with db() as c:
        c.execute("INSERT OR REPLACE INTO plans(id,created_at,status,request,result) VALUES (?,?,?,?,?)",
                  (plan_id, time.time(), status, req.model_dump_json(), result.model_dump_json()))


def load_plan(plan_id: str) -> tuple[PlanRequest, PlanResponse] | None:
    with db() as c:
        row = c.execute("SELECT request, result FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        return None
    return PlanRequest.model_validate_json(row["request"]), PlanResponse.model_validate_json(row["result"])


async def run_plan(ctx: AppContext, req: PlanRequest, progress: Optional[Progress] = None) -> PlanResponse:
    prog = progress or _noop
    plan_id = uuid.uuid4().hex[:12]
    today = today_dhaka()
    budget = TokenBudget(ctx.settings.llm_max_tokens_per_plan)

    # 1. understand the request (rules first, small LLM only if needed)
    with span("plan.parse"):
        if req.destination:
            dest = resolve(req.destination)
            if not dest:
                raise PlanError(f"Unknown destination '{req.destination}'.")
            start = req.start_date or today
            end = req.end_date or start + dt.timedelta(days=6)
            source = "request"
        else:
            try:
                parsed = await parse_request(req.query or "", ctx.llm, today, budget)
            except ParseError as exc:
                raise PlanError(str(exc)) from exc
            dest, start, end, source = parsed.dest, parsed.start, parsed.end, parsed.source
            start = req.start_date or start
            end = req.end_date or end
    last_day = today + dt.timedelta(days=15)
    start, end = max(start, today), min(end, last_day)
    if start > end:
        raise PlanError("Requested dates are outside the 16-day forecast window (today to +15 days).")
    days = [start + dt.timedelta(n) for n in range((end - start).days + 1)]
    await prog("parsed", f"{dest.name}, {start} to {end} (parsed by {source})")

    prefs = load_prefs(req.user_id)
    if req.risk_tolerance:
        prefs.risk_tolerance = req.risk_tolerance
    scales = scales_from(prefs)

    # 2. fetch everything in parallel
    await prog("fetching", "weather, waves, floods, alerts, earthquakes")
    with span("plan.fetch", dest=dest.key):
        try:
            bundle = await gather_data(ctx.http, dest, start, end, today)
        except UpstreamError as exc:
            raise PlanError(str(exc), status=502) from exc
    audit(plan_id, "data_fetched", {"refs": bundle.refs, "gaps": bundle.gaps})

    # 3. multi-agent analysis
    await prog("analyzing", "weather, safety, logistics and guide agents running")
    with span("plan.agents"):
        state = await run_agents({"ctx": ctx, "dest": dest, "days": days, "bundle": bundle, "scales": scales,
                                  "lang": req.language, "budget": budget})
    verdicts = state["final"]
    best, best_is_caution = state["best"], state["best_is_caution"]

    # 4. human-in-the-loop gate: never silently recommend a risky day
    needs_approval = bool(best_is_caution and not req.confirm_caution)
    question = None
    if needs_approval:
        top = next((d for d in verdicts if d.day == best[0]), verdicts[0])
        why = top.reasons[0].message if top.reasons else "conditions are borderline"
        question = (f"No day in your range is a clear 'go'. The least-risky option is {best[0]} "
                    f"({top.verdict.value}): {why} Do you want me to recommend it anyway?")
        audit(plan_id, "approval_requested", {"best": best, "question": question})

    response = PlanResponse(
        plan_id=plan_id, status="needs_approval" if needs_approval else "complete",
        destination=dest.name, destination_key=dest.key, start_date=start, end_date=end, days=verdicts,
        best_days=[] if needs_approval else best, best_is_caution=best_is_caution,
        avoid_days=[d.day for d in verdicts if d.verdict == Verdict.AVOID],
        narrative=state.get("narrative", ""), narrative_source=state.get("narrative_source", "template"),
        conflicts=state.get("conflicts", []), tips=state.get("tips", []), nearby_hospitals=state.get("hospitals", []),
        data_gaps=bundle.gaps + state.get("notes", []), approval_question=question, tokens_used=budget.used)
    _save(plan_id, response.status, req, response)
    audit(plan_id, "plan_created", {"status": response.status, "narrative_source": response.narrative_source,
                                    "tokens": budget.used})
    await prog("done", response.status)
    return response


def decide(plan_id: str, approved: bool, note: str = "") -> PlanResponse:
    """Resume a paused plan after the human's decision."""
    loaded = load_plan(plan_id)
    if not loaded:
        raise PlanError("Plan not found.", status=404)
    req, plan = loaded
    if plan.status != "needs_approval":
        raise PlanError(f"Plan is already '{plan.status}'.", status=409)
    if approved:
        from .scoring import pick_best
        best, _ = pick_best(plan.days)
        plan = plan.model_copy(update={"status": "complete", "best_days": best, "approval_question": None})
    else:
        plan = plan.model_copy(update={"status": "rejected", "best_days": [], "approval_question": None})
    _save(plan_id, plan.status, req, plan)
    audit(plan_id, "approved" if approved else "rejected", {"note": note})
    return plan


def audit_trail(plan_id: str) -> list[dict]:
    with db() as c:
        rows = c.execute("SELECT ts, event, detail FROM audit_log WHERE plan_id=? ORDER BY id", (plan_id,)).fetchall()
    return [{"ts": r["ts"], "event": r["event"], "detail": json.loads(r["detail"] or "null")} for r in rows]
