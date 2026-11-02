"""Model router: picks provider + model size per call, falls back on failure, enforces a token budget.

tier="small": cheap jobs (parsing requests, formatting)    tier="large": reasoning/writing jobs
Provider order comes from LLM_PROVIDER_ORDER. With no keys and no Ollama, callers get
LLMUnavailable and use deterministic templates, so the app always works offline-from-LLMs.
"""
from __future__ import annotations

import logging
import time

import httpx

from ..config import Settings, get_settings
from ..db import db
from .budget import TokenBudget, estimate_tokens
from .providers import BaseProvider, GeminiProvider, GroqProvider, LLMResult, OllamaProvider, ProviderError

log = logging.getLogger("jholokjatra.llm")


class LLMUnavailable(Exception):
    pass


class LLMRouter:
    def __init__(self, client: httpx.AsyncClient, settings: Settings | None = None):
        self.s = settings or get_settings()
        registry = {"groq": GroqProvider, "gemini": GeminiProvider, "ollama": OllamaProvider}
        self.providers: list[BaseProvider] = [
            registry[n](client, self.s) for n in self.s.provider_order if n in registry]

    def active(self) -> list[str]:
        return [p.name for p in self.providers if p.available()]

    async def complete(self, messages: list[dict], *, tier: str = "small", json_mode: bool = False,
                       max_tokens: int = 500, temperature: float = 0.2, budget: TokenBudget | None = None,
                       purpose: str = "") -> LLMResult:
        if budget:
            budget.check(estimate_tokens(messages, max_tokens))  # raises BudgetExceeded
        errors: list[str] = []
        for p in self.providers:
            if not p.available():
                continue
            ok, res = 0, None
            t0 = time.perf_counter()
            try:
                res = await p.chat(messages, tier, json_mode, max_tokens, temperature)
                ok = 1
            except ProviderError as exc:
                errors.append(str(exc))
                log.warning("LLM provider %s failed: %s", p.name, exc)
            self._record(p.name, p.model_for(tier), tier, purpose, res, ok, (time.perf_counter() - t0) * 1000)
            if res:
                if budget:
                    budget.charge(res.prompt_tokens, res.completion_tokens)
                return res
        raise LLMUnavailable("; ".join(errors) or "no LLM provider configured")

    @staticmethod
    def _record(provider, model, tier, purpose, res: LLMResult | None, ok: int, latency_ms: float) -> None:
        try:
            with db() as c:
                c.execute(
                    "INSERT INTO llm_usage(ts,provider,model,tier,purpose,prompt_tokens,completion_tokens,latency_ms,ok) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (time.time(), provider, model, tier, purpose, res.prompt_tokens if res else 0,
                     res.completion_tokens if res else 0, latency_ms, ok))
        except Exception:
            log.exception("failed to record llm usage")
