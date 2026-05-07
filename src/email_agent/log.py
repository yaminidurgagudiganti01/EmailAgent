"""Logging configuration for the email agent."""
from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj)


_configured = False


def setup_logging(
    log_dir: Path = Path("logs"),
    level: int = logging.DEBUG,
    fmt: str = "text",
) -> None:
    """Configure root logger with console + rotating file handler.

    fmt="json" emits newline-delimited JSON (for log aggregators).
    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _configured
    if _configured:
        return
    _configured = True

    log_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    root = logging.getLogger("email_agent")
    root.setLevel(level)
    root.propagate = False

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "email_agent.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
