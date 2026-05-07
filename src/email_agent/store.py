"""Idempotency store for processed email IDs.

Uses Supabase (Postgres) when DATABASE_URL is set, otherwise SQLite for local dev.
Interface is identical either way: is_processed / mark_processed / processed_count.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Postgres (Supabase)
# ---------------------------------------------------------------------------

if settings.database_url:
    try:
        import psycopg2
        import psycopg2.extras
        _USE_PG = True
        logger.debug("Store: using Postgres at %s", settings.database_url.split("@")[-1])
    except ImportError:
        logger.warning("psycopg2 not installed — falling back to SQLite store")
        _USE_PG = False
else:
    _USE_PG = False
    logger.debug("DATABASE_URL not set — using SQLite store at %s", settings.store_path)


@contextmanager
def _pg():
    conn = psycopg2.connect(settings.database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_pg_schema() -> None:
    with _pg() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_emails (
                    email_id     TEXT PRIMARY KEY,
                    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    draft_id     TEXT
                )
                """
            )


# ---------------------------------------------------------------------------
# SQLite (local dev fallback)
# ---------------------------------------------------------------------------

@contextmanager
def _sqlite():
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


def _ensure_sqlite_schema() -> None:
    with _sqlite() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_emails (
                email_id     TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL,
                draft_id     TEXT
            )
            """
        )


# ---------------------------------------------------------------------------
# Initialise whichever backend is active
# ---------------------------------------------------------------------------

if _USE_PG:
    _ensure_pg_schema()
else:
    _ensure_sqlite_schema()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def is_processed(email_id: str) -> bool:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM processed_emails WHERE email_id = %s", (email_id,)
                )
                return cur.fetchone() is not None
    else:
        with _sqlite() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_emails WHERE email_id = ?", (email_id,)
            ).fetchone()
        return row is not None


def mark_processed(email_id: str, draft_id: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO processed_emails (email_id, processed_at, draft_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (email_id) DO NOTHING
                    """,
                    (email_id, now, draft_id),
                )
    else:
        with _sqlite() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO processed_emails (email_id, processed_at, draft_id)
                VALUES (?, ?, ?)
                """,
                (email_id, now, draft_id),
            )
    logger.debug("Marked %s processed (draft=%s)", email_id, draft_id)


def processed_count() -> int:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM processed_emails")
                row = cur.fetchone()
        return row[0] if row else 0
    else:
        with _sqlite() as conn:
            row = conn.execute("SELECT COUNT(*) FROM processed_emails").fetchone()
        return row[0] if row else 0
