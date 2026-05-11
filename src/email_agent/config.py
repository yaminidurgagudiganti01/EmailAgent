"""Configuration loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root is two levels above this file: src/email_agent/config.py → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _abs(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    # LLM
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    # Gmail
    gmail_credentials_path: Path = field(
        default_factory=lambda: _abs(os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json"))
    )
    gmail_token_path: Path = field(
        default_factory=lambda: _abs(os.getenv("GMAIL_TOKEN_PATH", "config/token.json"))
    )

    # Storage — Postgres (Supabase) preferred; SQLite fallback when DATABASE_URL is empty
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    store_path: Path = field(
        default_factory=lambda: _abs(os.getenv("STORE_PATH", "data/processed.db"))
    )

    # Logging
    log_dir: Path = field(
        default_factory=lambda: _abs(os.getenv("LOG_DIR", "logs"))
    )
    log_format: str = field(
        default_factory=lambda: os.getenv("LOG_FORMAT", "text")  # "text" | "json"
    )

    # Agent behaviour
    max_emails_per_run: int = field(
        default_factory=lambda: int(os.getenv("MAX_EMAILS_PER_RUN", "10"))
    )
    inbox_query: str = field(
        default_factory=lambda: os.getenv(
            "INBOX_QUERY", "is:unread -category:promotions -category:social"
        )
    )
    user_name: str = field(default_factory=lambda: os.getenv("USER_NAME", "Me"))
    user_signature: str = field(
        default_factory=lambda: os.getenv("USER_SIGNATURE", "Best,\nMe").replace("\\n", "\n")
    )
    # 0 = scheduler disabled; >0 = run every N minutes automatically
    schedule_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("SCHEDULE_INTERVAL_MINUTES", "0"))
    )
    # Triage decisions below this threshold are flagged for human review (no auto-draft)
    confidence_threshold: float = field(
        default_factory=lambda: float(os.getenv("CONFIDENCE_THRESHOLD", "0.7"))
    )

    def validate(self) -> None:
        errors: list[str] = []

        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is not set")

        if not self.gmail_credentials_path.exists():
            errors.append(
                f"Gmail credentials not found at {self.gmail_credentials_path}. "
                "Download OAuth client JSON from Google Cloud Console and save it there."
            )

        if errors:
            msg = "Configuration errors:\n" + "\n".join(f"  • {e}" for e in errors)
            raise ValueError(msg)


settings = Settings()
