"""SQLite-backed store for processed email IDs.

Prevents duplicate drafts when the agent is re-run on the same inbox.
The DB file is created automatically on first use.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)


@contextmanager
def _db():
    settings.store_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.store_path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema() -> None:
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_emails (
                email_id     TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL,
                draft_id     TEXT
            )
            """
        )


_ensure_schema()


def is_processed(email_id: str) -> bool:
    """Return True if this email has already been fully processed."""
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,)
        ).fetchone()
    return row is not None


def mark_processed(email_id: str, draft_id: str | None = None) -> None:
    """Record that an email has been processed (with an optional draft ID)."""
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO processed_emails (email_id, processed_at, draft_id)
            VALUES (?, ?, ?)
            """,
            (email_id, now, draft_id),
        )
    logger.debug("Marked %s as processed (draft=%s)", email_id, draft_id)


def processed_count() -> int:
    """Return total number of processed emails recorded."""
    with _db() as conn:
        row = conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()
    return row[0] if row else 0
