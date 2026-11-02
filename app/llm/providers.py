"""Thin async clients for Groq, Gemini and Ollama. API keys travel in headers, never in URLs."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from ..config import Settings


class ProviderError(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float


class BaseProvider:
    name = "base"

    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.s = client, settings

    def available(self) -> bool:
        raise NotImplementedError

    def model_for(self, tier: str) -> str:
        raise NotImplementedError

    async def chat(self, messages: list[dict], tier: str, json_mode: bool, max_tokens: int,
                   temperature: float) -> LLMResult:
        raise NotImplementedError

    async def _post(self, url: str, headers: dict, body: dict) -> dict:
        try:
            r = await self.client.post(url, headers=headers, json=body, timeout=60)
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} transport error: {type(exc).__name__}") from exc
        if r.status_code >= 400:
            raise ProviderError(f"{self.name} HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as exc:
            raise ProviderError(f"{self.name} returned non-JSON") from exc


class GroqProvider(BaseProvider):
    name = "groq"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def available(self) -> bool:
        return bool(self.s.groq_api_key)

    def model_for(self, tier: str) -> str:
        return self.s.groq_model_large if tier == "large" else self.s.groq_model_small

    async def chat(self, messages, tier, json_mode, max_tokens, temperature) -> LLMResult:
        model = self.model_for(tier)
        if "gpt-oss" in model:
            # Reasoning models spend completion tokens on hidden thinking before the answer; a small
            # max_tokens can leave the visible answer empty. Give headroom and keep thinking short.
            max_tokens = max(1024, max_tokens * 3)
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if "gpt-oss" in model:
            body["reasoning_effort"] = self.s.groq_reasoning_effort
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        d = await self._post(self.URL, {"Authorization": f"Bearer {self.s.groq_api_key}"}, body)
        try:
            text = d["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("groq: unexpected response shape") from exc
        if not text.strip():
            raise ProviderError("groq: empty answer (reasoning used all tokens?); raise max tokens or lower reasoning effort")
        u = d.get("usage", {})
        return LLMResult(text, self.name, model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
                         (time.perf_counter() - t0) * 1000)


class GeminiProvider(BaseProvider):
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def available(self) -> bool:
        return bool(self.s.gemini_api_key)

    def model_for(self, tier: str) -> str:
        return self.s.gemini_model_large if tier == "large" else self.s.gemini_model_small

    async def chat(self, messages, tier, json_mode, max_tokens, temperature) -> LLMResult:
        model = self.model_for(tier)
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in messages if m["role"] != "system"]
        cfg: dict = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            cfg["responseMimeType"] = "application/json"
        body: dict = {"contents": contents, "generationConfig": cfg}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        t0 = time.perf_counter()
        d = await self._post(f"{self.BASE}/{model}:generateContent", {"x-goog-api-key": self.s.gemini_api_key}, body)
        try:
            text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("gemini: empty/blocked response") from exc
        u = d.get("usageMetadata", {})
        return LLMResult(text, self.name, model, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0),
                         (time.perf_counter() - t0) * 1000)


class OllamaProvider(BaseProvider):
    name = "ollama"

    def available(self) -> bool:
        return self.s.ollama_enabled

    def model_for(self, tier: str) -> str:
        return self.s.ollama_model_large if tier == "large" else self.s.ollama_model_small

    async def chat(self, messages, tier, json_mode, max_tokens, temperature) -> LLMResult:
        model = self.model_for(tier)
        body = {"model": model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if json_mode:
            body["format"] = "json"
        t0 = time.perf_counter()
        d = await self._post(f"{self.s.ollama_host}/api/chat", {}, body)
        try:
            text = d["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("ollama: unexpected response shape") from exc
        return LLMResult(text, self.name, model, d.get("prompt_eval_count", 0), d.get("eval_count", 0),
                         (time.perf_counter() - t0) * 1000)
