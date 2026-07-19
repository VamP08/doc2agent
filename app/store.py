"""SQLite persistence for agent sessions — sessions survive server restarts."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get(
    "DOC2AGENT_DB", str(Path(__file__).resolve().parent.parent / "doc2agent.db")
)
MAX_SESSIONS = 200

_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions ("
        "  id TEXT PRIMARY KEY,"
        "  created_at TEXT NOT NULL,"
        "  updated_at TEXT NOT NULL,"
        "  payload TEXT NOT NULL)"
    )
    return conn


def save_session(session_id: str, payload: dict) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, updated_at, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (session_id, now, now, json.dumps(payload)),
        )
        # keep the table bounded at demo scale
        conn.execute(
            "DELETE FROM sessions WHERE id NOT IN "
            "(SELECT id FROM sessions ORDER BY updated_at DESC LIMIT ?)",
            (MAX_SESSIONS,),
        )


def load_session(session_id: str) -> dict | None:
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT payload FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return json.loads(row[0]) if row else None
