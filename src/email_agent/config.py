"""Configuration loaded from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))

    gmail_credentials_path: Path = field(
        default_factory=lambda: Path(os.getenv("GMAIL_CREDENTIALS_PATH", "./config/credentials.json"))
    )
    gmail_token_path: Path = field(
        default_factory=lambda: Path(os.getenv("GMAIL_TOKEN_PATH", "./config/token.json"))
    )
    store_path: Path = field(
        default_factory=lambda: Path(os.getenv("STORE_PATH", "./data/processed.db"))
    )
    log_dir: Path = field(
        default_factory=lambda: Path(os.getenv("LOG_DIR", "./logs"))
    )

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

    def validate(self) -> None:
        """Raise ValueError early if required config is missing or invalid."""
        errors: list[str] = []

        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is not set — add it to your .env file")

        if not self.gmail_credentials_path.exists():
            errors.append(
                f"Gmail credentials not found at {self.gmail_credentials_path}. "
                "Download OAuth client JSON from Google Cloud Console and save it there."
            )

        if errors:
            msg = "Configuration errors:\n" + "\n".join(f"  • {e}" for e in errors)
            raise ValueError(msg)


settings = Settings()
