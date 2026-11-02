"""Structured output with validation + error recovery: invalid JSON is fed back to the model."""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .budget import TokenBudget
from .router import LLMRouter

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def extract_json(text: str) -> dict:
    t = _FENCE.sub("", text.strip())
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(t[start:end + 1])


async def structured_call(router: LLMRouter, model_cls: type[T], messages: list[dict], *, tier: str = "small",
                          budget: TokenBudget | None = None, retries: int = 2, max_tokens: int = 400,
                          purpose: str = "") -> T:
    msgs = list(messages)
    last: Exception | None = None
    for _ in range(retries + 1):
        res = await router.complete(msgs, tier=tier, json_mode=True, max_tokens=max_tokens, budget=budget,
                                    purpose=purpose)
        try:
            return model_cls.model_validate(extract_json(res.text))
        except (ValueError, ValidationError) as exc:
            last = exc
            msgs = msgs + [
                {"role": "assistant", "content": res.text[:800]},
                {"role": "user", "content": f"That was invalid: {str(exc)[:300]}. "
                                            "Reply again with ONLY a valid JSON object matching the schema."},
            ]
    raise ValueError(f"structured output failed after {retries + 1} attempts: {last}")
