"""SQLite storage for Runway. One file, shared by the web and Telegram processes."""
from __future__ import annotations
import os, sqlite3, threading, json
from pathlib import Path

DB_PATH = os.getenv("RUNWAY_DB", str(Path(__file__).resolve().parent.parent / "runway.db"))
_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS commitments (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  what TEXT NOT NULL,
  due TEXT,
  due_fuzziness TEXT,
  people TEXT NOT NULL DEFAULT '[]',
  type TEXT NOT NULL DEFAULT 'promise',
  est_minutes INTEGER NOT NULL DEFAULT 30,
  first_step TEXT,
  state TEXT NOT NULL DEFAULT 'hidden',     -- hidden | now | done | slipped | closed
  surfaced_at TEXT,
  started_at TEXT,
  checkin_sent INTEGER NOT NULL DEFAULT 0,
  draft TEXT,
  created_at TEXT NOT NULL,
  source TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  commitment_id TEXT,
  user_id TEXT NOT NULL,
  est_minutes INTEGER NOT NULL,
  actual_minutes INTEGER NOT NULL,
  completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS channels (
  user_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  PRIMARY KEY (user_id, channel)
);
CREATE TABLE IF NOT EXISTS aliases (
  alias TEXT PRIMARY KEY,
  canonical TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
  user_id TEXT NOT NULL,
  name_lower TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  PRIMARY KEY (user_id, name_lower)
);
CREATE TABLE IF NOT EXISTS prefs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  user_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON outbox(channel, delivered_at);
CREATE INDEX IF NOT EXISTS idx_commit_user_state ON commitments(user_id, state);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None, timeout=10)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA busy_timeout=5000")
            _conn.executescript(SCHEMA)
        return _conn


def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        return conn().execute(sql, params).fetchall()


def one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def x(sql: str, params: tuple = ()) -> int:
    with _lock:
        cur = conn().execute(sql, params)
        return cur.lastrowid or cur.rowcount


def row_to_dict(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    if "people" in d and isinstance(d["people"], str):
        try:
            d["people"] = json.loads(d["people"])
        except Exception:
            d["people"] = []
    return d


def pref_get(key: str, default: str | None = None) -> str | None:
    r = one("SELECT value FROM prefs WHERE key=?", (key,))
    return r["value"] if r else default


def pref_set(key: str, value) -> None:
    x("INSERT INTO prefs(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, str(value)))
