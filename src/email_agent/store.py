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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS processed_emails (
                    email_id     TEXT PRIMARY KEY,
                    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    draft_id     TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sent_emails (
                    message_id TEXT PRIMARY KEY,
                    email_id   TEXT,
                    sent_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    subject    TEXT,
                    to_addr    TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS email_log (
                    id         BIGSERIAL PRIMARY KEY,
                    email_id   TEXT NOT NULL,
                    from_addr  TEXT,
                    subject    TEXT,
                    category   TEXT,
                    priority   TEXT,
                    draft_id   TEXT,
                    sent       BOOLEAN DEFAULT FALSE,
                    logged_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exclude_rules (
                    id         BIGSERIAL PRIMARY KEY,
                    rule_type  TEXT NOT NULL,
                    value      TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(rule_type, value)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_style (
                    id         INT PRIMARY KEY DEFAULT 1,
                    profile    TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kb_entries (
                    id         BIGSERIAL PRIMARY KEY,
                    title      TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)


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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                email_id     TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL,
                draft_id     TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sent_emails (
                message_id TEXT PRIMARY KEY,
                email_id   TEXT,
                sent_at    TEXT NOT NULL,
                subject    TEXT,
                to_addr    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id  TEXT NOT NULL,
                from_addr TEXT,
                subject   TEXT,
                category  TEXT,
                priority  TEXT,
                draft_id  TEXT,
                sent      INTEGER DEFAULT 0,
                logged_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS exclude_rules (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_type  TEXT NOT NULL,
                value      TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(rule_type, value)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_style (
                id         INTEGER PRIMARY KEY DEFAULT 1,
                profile    TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


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


def mark_sent(message_id: str, email_id: str | None, subject: str, to_addr: str) -> None:
    """Record a sent email."""
    now = datetime.now(timezone.utc).isoformat()
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sent_emails (message_id, email_id, sent_at, subject, to_addr)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    (message_id, email_id, now, subject, to_addr),
                )
    else:
        with _sqlite() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sent_emails (message_id, email_id, sent_at, subject, to_addr)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, email_id, now, subject, to_addr),
            )
    logger.debug("Recorded sent email %s — %r", message_id, subject)


def sent_count() -> int:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM sent_emails")
                row = cur.fetchone()
        return row[0] if row else 0
    else:
        with _sqlite() as conn:
            row = conn.execute("SELECT COUNT(*) FROM sent_emails").fetchone()
        return row[0] if row else 0


# ---------------------------------------------------------------------------
# Email log
# ---------------------------------------------------------------------------

def log_email(
    email_id: str,
    from_addr: str,
    subject: str,
    category: str,
    priority: str,
    draft_id: str | None = None,
    sent: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO email_log
                        (email_id, from_addr, subject, category, priority, draft_id, sent, logged_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (email_id, from_addr, subject, category, priority, draft_id, sent, now),
                )
    else:
        with _sqlite() as conn:
            conn.execute(
                """
                INSERT INTO email_log
                    (email_id, from_addr, subject, category, priority, draft_id, sent, logged_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (email_id, from_addr, subject, category, priority, draft_id, int(sent), now),
            )


def get_email_log(limit: int = 100) -> list[dict]:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT email_id, from_addr, subject, category, priority,
                           draft_id, sent, logged_at
                    FROM email_log ORDER BY logged_at DESC LIMIT %s
                    """,
                    (limit,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    else:
        with _sqlite() as conn:
            rows = conn.execute(
                """
                SELECT email_id, from_addr, subject, category, priority,
                       draft_id, sent, logged_at
                FROM email_log ORDER BY logged_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        cols = ["email_id", "from_addr", "subject", "category", "priority",
                "draft_id", "sent", "logged_at"]
        rows_out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["sent"] = bool(d["sent"])  # SQLite stores 0/1; convert to bool
            rows_out.append(d)
        return rows_out


def update_log_sent(email_id: str) -> None:
    """Mark an existing email_log row as sent=True."""
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE email_log SET sent=TRUE WHERE email_id=%s", (email_id,))
    else:
        with _sqlite() as conn:
            conn.execute("UPDATE email_log SET sent=1 WHERE email_id=?", (email_id,))


# ---------------------------------------------------------------------------
# Exclude rules
# ---------------------------------------------------------------------------

def get_exclude_rules() -> list[dict]:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, rule_type, value, created_at FROM exclude_rules ORDER BY id")
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    else:
        with _sqlite() as conn:
            rows = conn.execute(
                "SELECT id, rule_type, value, created_at FROM exclude_rules ORDER BY id"
            ).fetchall()
        return [{"id": r[0], "rule_type": r[1], "value": r[2], "created_at": r[3]} for r in rows]


def add_exclude_rule(rule_type: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO exclude_rules (rule_type, value, created_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (rule_type, value.lower(), now),
                )
    else:
        with _sqlite() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO exclude_rules (rule_type, value, created_at) VALUES (?,?,?)",
                (rule_type, value.lower(), now),
            )


def remove_exclude_rule(rule_id: int) -> None:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM exclude_rules WHERE id = %s", (rule_id,))
    else:
        with _sqlite() as conn:
            conn.execute("DELETE FROM exclude_rules WHERE id = ?", (rule_id,))


def is_excluded(from_addr: str, category: str, rules: list[dict]) -> bool:
    addr = from_addr.lower()
    cat  = category.lower()
    for rule in rules:
        v = rule["value"]
        if rule["rule_type"] == "sender"   and v in addr:
            return True
        if rule["rule_type"] == "domain"   and addr.endswith(f"@{v}") or addr.endswith(f"<{v}>"):
            return True
        if rule["rule_type"] == "category" and v == cat:
            return True
    return False


# ---------------------------------------------------------------------------
# Style profile
# ---------------------------------------------------------------------------

def get_style_profile() -> str | None:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT profile FROM user_style WHERE id=1")
                row = cur.fetchone()
        return row[0] if row else None
    else:
        with _sqlite() as conn:
            row = conn.execute("SELECT profile FROM user_style WHERE id=1").fetchone()
        return row[0] if row else None


def save_style_profile(profile: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_style (id, profile, updated_at) VALUES (1,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET profile=EXCLUDED.profile, updated_at=EXCLUDED.updated_at
                    """,
                    (profile, now),
                )
    else:
        with _sqlite() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_style (id, profile, updated_at) VALUES (1,?,?)",
                (profile, now),
            )


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

def get_kb() -> list[dict]:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, title, content, created_at FROM kb_entries ORDER BY id")
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
    else:
        with _sqlite() as conn:
            rows = conn.execute(
                "SELECT id, title, content, created_at FROM kb_entries ORDER BY id"
            ).fetchall()
        return [{"id": r[0], "title": r[1], "content": r[2], "created_at": r[3]} for r in rows]


def add_kb_entry(title: str, content: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO kb_entries (title, content, created_at) VALUES (%s,%s,%s)",
                    (title, content, now),
                )
    else:
        with _sqlite() as conn:
            conn.execute(
                "INSERT INTO kb_entries (title, content, created_at) VALUES (?,?,?)",
                (title, content, now),
            )


def delete_kb_entry(entry_id: int) -> None:
    if _USE_PG:
        with _pg() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM kb_entries WHERE id=%s", (entry_id,))
    else:
        with _sqlite() as conn:
            conn.execute("DELETE FROM kb_entries WHERE id=?", (entry_id,))
