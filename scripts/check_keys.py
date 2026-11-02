"""Verify your Groq / Gemini keys work (lists models; does not spend tokens).   python -m scripts.check_keys"""
import asyncio

import httpx

from app.config import get_settings


async def main() -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=15) as c:
        for name, key, url, hdr in [
            ("Groq", s.groq_api_key, "https://api.groq.com/openai/v1/models", {"Authorization": f"Bearer {s.groq_api_key}"}),
            ("Gemini", s.gemini_api_key, "https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": s.gemini_api_key}),
        ]:
            if not key:
                print(f"[--] {name}: no key set in .env (that's fine, it will be skipped)")
                continue
            try:
                r = await c.get(url, headers=hdr)
                if r.status_code == 200:
                    items = r.json().get("data") or r.json().get("models") or []
                    print(f"[OK] {name}: key valid, {len(items)} models visible")
                else:
                    print(f"[XX] {name}: HTTP {r.status_code} - {r.text[:150]}")
            except httpx.HTTPError as exc:
                print(f"[XX] {name}: network error {type(exc).__name__}")
    print(f"Provider order: {s.provider_order}; Ollama enabled: {s.ollama_enabled}")


if __name__ == "__main__":
    asyncio.run(main())
