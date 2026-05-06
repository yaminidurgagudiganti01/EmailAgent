"""Logging configuration for the email agent."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_configured = False


def setup_logging(log_dir: Path = Path("logs"), level: int = logging.DEBUG) -> None:
    """Configure root logger with a console handler (INFO) and rotating file handler (DEBUG).

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("email_agent")
    root.setLevel(level)
    # Prevent log records from propagating to the root logger (avoids duplicates).
    root.propagate = False

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "email_agent.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)
