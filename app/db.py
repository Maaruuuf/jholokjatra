"""Tiny SQLite layer. One short-lived connection per operation (WAL mode) keeps it thread-safe."""
import sqlite3
from contextlib import contextmanager

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    key TEXT PRIMARY KEY, url TEXT NOT NULL, body TEXT NOT NULL, fetched_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS plans (
    id TEXT PRIMARY KEY, created_at REAL NOT NULL, status TEXT NOT NULL,
    request TEXT NOT NULL, result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, plan_id TEXT, event TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS preferences (user_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, name TEXT NOT NULL,
    duration_ms REAL NOT NULL, ok INTEGER NOT NULL, attrs TEXT);
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, provider TEXT, model TEXT, tier TEXT,
    purpose TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms REAL, ok INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tips (
    dest TEXT NOT NULL, idx INTEGER NOT NULL, text TEXT NOT NULL, url TEXT, PRIMARY KEY (dest, idx));
"""


@contextmanager
def db():
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()
