"""Wikivoyage plain-text extract via the MediaWiki API (CC BY-SA content: keep the attribution URL)."""
import httpx

from ..config import get_settings
from ..http import fetch_json

API = "https://en.wikivoyage.org/w/api.php"


async def get_extract(client: httpx.AsyncClient, title: str) -> tuple[str, str]:
    f = await fetch_json(client, API, {
        "action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
        "format": "json", "redirects": 1}, ttl=get_settings().ttl_static)
    pages = (f.data.get("query") or {}).get("pages") or {}
    text = next((p.get("extract", "") for p in pages.values()), "")
    return text, f"https://en.wikivoyage.org/wiki/{title.replace(' ', '_')}"
