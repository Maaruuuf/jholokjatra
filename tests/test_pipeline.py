import datetime as dt

import httpx
import pytest

from app.main import app
from app.pipeline import PlanError, audit_trail, decide, run_plan
from app.schemas import PlanRequest, Verdict
from app.tools.registry import call_tool, today_dhaka, tool_schemas


async def test_plan_flags_storm_day_and_cites_evidence(ctx, world):
    res = await run_plan(ctx, PlanRequest(destination="coxs_bazar", language="en"))
    assert res.status == "complete"
    storm = today_dhaka() + dt.timedelta(days=3)
    by_day = {d.day: d for d in res.days}
    assert by_day[storm].verdict == Verdict.AVOID and storm in res.avoid_days
    assert storm not in res.best_days and res.best_days
    assert all(r.ref for d in res.days for r in d.reasons)  # every reason is cited
    assert res.narrative_source.startswith("template")  # no LLM keys configured
    assert res.nearby_hospitals and res.nearby_hospitals[0].name == "Sadar Hospital"


async def test_untrusted_tip_text_is_sanitised(ctx):
    res = await run_plan(ctx, PlanRequest(destination="coxs_bazar"))
    blob = " ".join(t.text for t in res.tips).lower()
    assert "ignore all previous" not in blob and res.tips


async def test_gdacs_red_cyclone_creates_conflict_and_veto(ctx, world):
    today = today_dhaka()
    world.storm_offset = None
    world.gdacs = [{"properties": {"eventtype": "TC", "name": "TESTSTORM", "alertlevel": "Red",
                                   "fromdate": today.isoformat(), "todate": (today + dt.timedelta(3)).isoformat()},
                    "geometry": {"type": "Point", "coordinates": [91.9, 21.3]}}]
    res = await run_plan(ctx, PlanRequest(destination="coxs_bazar"))
    assert res.days[0].verdict == Verdict.AVOID
    assert res.conflicts and "Safety veto" in res.conflicts[0]


async def test_human_approval_gate_pause_and_resume(ctx, world):
    world.storm_offset, world.all_wet = None, True  # every day is "caution"
    res = await run_plan(ctx, PlanRequest(destination="sajek"))
    assert res.status == "needs_approval" and res.best_days == [] and res.approval_question
    done = decide(res.plan_id, True, "ok, I accept the risk")
    assert done.status == "complete" and done.best_days
    events = [e["event"] for e in audit_trail(res.plan_id)]
    assert events[-3:] == ["approval_requested", "plan_created", "approved"] or "approved" in events
    with pytest.raises(PlanError):
        decide(res.plan_id, True)  # already decided


async def test_confirm_caution_skips_gate(ctx, world):
    world.storm_offset, world.all_wet = None, True
    res = await run_plan(ctx, PlanRequest(destination="sajek", confirm_caution=True))
    assert res.status == "complete" and res.best_days and res.best_is_caution


async def test_forecast_outage_returns_502(ctx, world):
    world.fail_forecast = True
    with pytest.raises(PlanError) as e:
        await run_plan(ctx, PlanRequest(destination="sajek"))
    assert e.value.status == 502


async def test_free_text_query(ctx):
    res = await run_plan(ctx, PlanRequest(query="কক্সবাজার next 4 days"))
    assert res.destination_key == "coxs_bazar" and len(res.days) == 4


async def test_dates_outside_window_rejected(ctx):
    with pytest.raises(PlanError):
        await run_plan(ctx, PlanRequest(destination="sajek", start_date=dt.date(2020, 1, 1), end_date=dt.date(2020, 1, 3)))


async def test_llm_narrative_with_hallucinated_number_falls_back(groq_ctx, world):
    world.groq_replies = ["Go on day 1. Expect 999 mm of rain!", "Still 999 mm of rain."]
    res = await run_plan(groq_ctx, PlanRequest(destination="coxs_bazar"))
    assert "verification" in res.narrative_source and "999" not in res.narrative


async def test_llm_narrative_with_clean_numbers_is_used(groq_ctx, world):
    world.groq_replies = ["Avoid the stormy day because rainfall 80 mm and gusts 75 km/h are forecast."]
    res = await run_plan(groq_ctx, PlanRequest(destination="coxs_bazar"))
    assert res.narrative_source.startswith("llm:groq") and res.tokens_used > 0


async def test_tools_validate_and_recover(ctx):
    bad = await call_tool(ctx, "get_forecast", {"destination": "sajek", "days": 99})
    assert not bad.ok and "days" in bad.error
    unknown = await call_tool(ctx, "get_forecast", {"destination": "atlantis"})
    assert not unknown.ok and "Valid destinations" in unknown.error
    ok = await call_tool(ctx, "get_forecast", {"destination": "sajek", "days": 3})
    assert ok.ok and len(ok.data["days"]) == 3
    assert {t["function"]["name"] for t in tool_schemas()} >= {"assess_days", "get_marine", "find_nearby"}


async def test_react_loop_calls_tool_then_answers(groq_ctx, world):
    from app.agents.react import run_react
    world.groq_replies = [
        '{"thought": "need forecast", "tool": "get_forecast", "args": {"destination": "sajek", "days": 2}}',
        '{"thought": "done", "final": "Sajek looks fine for the next two days."}']
    r = await run_react(groq_ctx, "Is Sajek okay this week?")
    assert not r.degraded and r.steps[0]["tool"] == "get_forecast" and r.steps[0]["ok"]


async def test_react_recovers_from_bad_json_and_degrades_at_cap(groq_ctx, world):
    from app.agents.react import MAX_ITERS, run_react
    world.groq_replies = ['{"thought": "x", "tool": "get_forecast", "args": {"destination": "sajek"}}'] * (MAX_ITERS + 1)
    r = await run_react(groq_ctx, "loop forever")
    assert r.degraded and len(r.steps) == MAX_ITERS


async def test_react_without_llm_degrades(ctx):
    from app.agents.react import run_react
    r = await run_react(ctx, "anything")
    assert r.degraded


async def test_api_end_to_end_with_evidence_endpoint(ctx):
    app.state.ctx = ctx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/health")).json()["status"] == "ok"
        r = await c.post("/plan", json={"destination": "coxs_bazar"})
        assert r.status_code == 200
        ref = next(x["ref"] for d in r.json()["days"] for x in d["reasons"])
        raw = await c.get(f"/evidence/{ref}")
        assert raw.status_code == 200 and "url" in raw.json()
        assert (await c.post("/plan", json={"query": "to the moon"})).status_code == 422
        assert (await c.post("/plan", json={})).status_code == 422
        assert (await c.get("/plans/nope")).status_code == 404
        put = await c.put("/preferences/u1", json={"motion_sickness": True, "risk_tolerance": "low"})
        assert put.json()["motion_sickness"] is True
        assert "spans" in (await c.get("/metrics")).json()
        sse = await c.get("/plan/stream", params={"destination": "sajek"})
        assert "event: fetching" in sse.text and "event: result" in sse.text


async def test_broken_vector_index_does_not_lose_tips(ctx, monkeypatch):
    """Regression: a failing/slow Chroma download must not drop the tips step."""
    from app.memory import tips as tips_mem

    class Broken:
        def upsert(self, **kw):
            raise TimeoutError("model download failed")

        def query(self, **kw):
            raise TimeoutError("model download failed")

    monkeypatch.setattr(tips_mem, "_chroma", lambda: Broken())
    res = await run_plan(ctx, PlanRequest(destination="coxs_bazar"))
    assert res.tips and not any("tips unavailable" in g for g in res.data_gaps)


async def test_gpt_oss_gets_reasoning_headroom(groq_ctx, world):
    sent = {}
    orig = world.handler

    def spy(request):
        if request.url.host == "api.groq.com":
            import json
            sent.update(json.loads(request.content))
        return orig(request)

    groq_ctx.http._transport = __import__("httpx").MockTransport(spy)
    await groq_ctx.llm.complete([{"role": "user", "content": "hi"}], tier="large", max_tokens=100)
    assert sent["model"] == "openai/gpt-oss-120b" and sent["reasoning_effort"] == "low" and sent["max_tokens"] >= 1024
