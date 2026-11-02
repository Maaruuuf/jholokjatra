import asyncio
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import __version__
from ..agents.react import run_react
from ..context import AppContext
from ..destinations import DESTINATIONS
from ..http import get_raw
from ..memory.prefs import load_prefs, save_prefs
from ..pipeline import PlanError, audit_trail, decide, load_plan, run_plan
from ..schemas import AskRequest, AskResponse, DecisionRequest, PlanRequest, PlanResponse, Preferences
from ..tools.registry import TOOLS, ToolResult, call_tool, tool_schemas
from ..tracing import metrics_summary

router = APIRouter()


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


@router.get("/health")
async def health(ctx: AppContext = Depends(get_ctx)):
    return {"status": "ok", "version": __version__, "llm_providers": ctx.llm.active() or ["none (template mode)"]}


@router.get("/destinations")
async def destinations():
    return [{"key": d.key, "name": d.name, "name_bn": d.name_bn, "lat": d.lat, "lon": d.lon,
             "sea": d.sea_point is not None} for d in DESTINATIONS.values()]


@router.post("/plan", response_model=PlanResponse)
async def plan(req: PlanRequest, ctx: AppContext = Depends(get_ctx)):
    try:
        return await run_plan(ctx, req)
    except PlanError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/plan/stream")
async def plan_stream(request: Request, destination: Optional[str] = None, query: Optional[str] = None,
                      start_date: Optional[str] = None, end_date: Optional[str] = None, language: str = "en",
                      user_id: str = "default", ctx: AppContext = Depends(get_ctx)):
    """Server-Sent Events: progress events while the plan runs, then a final `done` event with the result."""
    try:
        req = PlanRequest(destination=destination, query=query, start_date=start_date, end_date=end_date,
                          language=language, user_id=user_id)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    queue: asyncio.Queue = asyncio.Queue()

    async def progress(stage: str, detail: str = "") -> None:
        await queue.put({"stage": stage, "detail": detail})

    async def worker():
        try:
            result = await run_plan(ctx, req, progress)
            await queue.put({"stage": "result", "result": result.model_dump(mode="json")})
        except PlanError as exc:
            await queue.put({"stage": "error", "detail": str(exc)})
        finally:
            await queue.put(None)

    task = asyncio.create_task(worker())

    async def gen():
        try:
            while (item := await queue.get()) is not None:
                yield f"event: {item['stage']}\ndata: {json.dumps(item, default=str)}\n\n"
        finally:
            await task

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: str):
    loaded = load_plan(plan_id)
    if not loaded:
        raise HTTPException(404, "Plan not found")
    return loaded[1]


@router.post("/plans/{plan_id}/decision", response_model=PlanResponse)
async def plan_decision(plan_id: str, body: DecisionRequest):
    try:
        return decide(plan_id, body.approved, body.note)
    except PlanError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/plans/{plan_id}/audit")
async def plan_audit(plan_id: str):
    return audit_trail(plan_id)


@router.get("/evidence/{ref}")
async def evidence(ref: str):
    raw = get_raw(ref)
    if not raw:
        raise HTTPException(404, "No stored response with that ref")
    return raw


@router.get("/tools")
async def list_tools():
    return tool_schemas()


@router.post("/tools/{name}", response_model=ToolResult)
async def run_tool(name: str, args: dict, ctx: AppContext = Depends(get_ctx)):
    if name not in TOOLS:
        raise HTTPException(404, f"Unknown tool. Available: {', '.join(TOOLS)}")
    return await call_tool(ctx, name, args)


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, ctx: AppContext = Depends(get_ctx)):
    return await run_react(ctx, body.question)


@router.get("/preferences/{user_id}", response_model=Preferences)
async def get_preferences(user_id: str):
    return load_prefs(user_id)


@router.put("/preferences/{user_id}", response_model=Preferences)
async def put_preferences(user_id: str, prefs: Preferences):
    return save_prefs(user_id, prefs)


@router.get("/metrics")
async def metrics():
    return metrics_summary()
