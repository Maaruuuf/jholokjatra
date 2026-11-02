"""Travel-tip memory built from Wikivoyage.

Chunks live in SQLite (always works). If `chromadb` is installed (requirements-memory.txt) they are also
indexed for semantic search; otherwise a keyword-overlap search is used. All text is sanitised at ingest.
"""
from __future__ import annotations

import logging
import re

import httpx

from ..clients import wikivoyage
from ..config import get_settings
from ..db import db
from ..destinations import Destination
from ..schemas import Tip
from ..security.sanitize import sanitize_untrusted

log = logging.getLogger("jholokjatra.tips")
_WORD = re.compile(r"[a-z]{3,}")
_collection = None


def _chroma():
    global _collection
    if not get_settings().use_chroma:
        return False
    if _collection is not None:
        return _collection
    try:
        import chromadb  # type: ignore
        s = get_settings()
        s.chroma_dir.mkdir(parents=True, exist_ok=True)
        _collection = chromadb.PersistentClient(path=str(s.chroma_dir)).get_or_create_collection("tips")
    except Exception as exc:  # not installed or failed to init
        log.info("Chroma unavailable (%s); using keyword search", type(exc).__name__)
        _collection = False
    return _collection


def clean_paragraphs(text: str) -> list[str]:
    """Split into paragraphs and DROP any paragraph that looks like a prompt-injection attempt."""
    out = []
    for p in re.split(r"\n\s*\n", text):
        p = p.strip()
        if len(p) <= 60 or p.startswith("=="):
            continue
        clean, flags = sanitize_untrusted(p, max_len=700)
        if not flags:
            out.append(clean)
    return out


def chunk_text(text: str, size: int = 600) -> list[str]:
    paras = clean_paragraphs(text)
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) > size and cur:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{p}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def _count(dest_key: str) -> int:
    with db() as c:
        return c.execute("SELECT COUNT(*) n FROM tips WHERE dest=?", (dest_key,)).fetchone()["n"]


async def ensure_indexed(client: httpx.AsyncClient, dest: Destination) -> None:
    import asyncio
    if await asyncio.to_thread(_count, dest.key):
        return
    text, url = await wikivoyage.get_extract(client, dest.wikivoyage)
    clean = chunk_text(text)[:40]
    with db() as c:
        c.executemany("INSERT OR REPLACE INTO tips(dest,idx,text,url) VALUES (?,?,?,?)",
                      [(dest.key, i, t, url) for i, t in enumerate(clean)])
    col = _chroma()
    if col and clean:
        try:
            col.upsert(ids=[f"{dest.key}-{i}" for i in range(len(clean))], documents=clean,
                       metadatas=[{"dest": dest.key, "url": url}] * len(clean))
        except Exception as exc:  # vector index is an optional upgrade; SQLite copy is enough
            log.warning("chroma upsert failed (%s); using keyword search", type(exc).__name__)


def search(dest_key: str, query: str, k: int = 3) -> list[Tip]:
    col = _chroma()
    if col:
        try:
            r = col.query(query_texts=[query], n_results=k, where={"dest": dest_key})
            return [Tip(text=d, url=m.get("url", "")) for d, m in zip(r["documents"][0], r["metadatas"][0])]
        except Exception as exc:
            log.warning("chroma query failed: %s", exc)
    q = set(_WORD.findall(query.lower()))
    with db() as c:
        rows = c.execute("SELECT text, url FROM tips WHERE dest=?", (dest_key,)).fetchall()
    scored = sorted(rows, key=lambda r: -len(q & set(_WORD.findall(r["text"].lower()))))
    return [Tip(text=r["text"], url=r["url"] or "") for r in scored[:k]]
