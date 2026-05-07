"""Health check — exits 0 if healthy, 1 if not.

Usage:
    python -m email_agent.health

Docker HEALTHCHECK calls this indirectly via the Streamlit /_stcore/health
endpoint, but this module is useful for local diagnostics.
"""
from __future__ import annotations

import sys


def check() -> list[str]:
    """Return a list of failure reasons. Empty list means healthy."""
    failures: list[str] = []

    # Config
    try:
        from .config import settings
        settings.validate()
    except ValueError as e:
        failures.append(f"config: {e}")
    except Exception as e:
        failures.append(f"config load error: {e}")
        return failures  # can't proceed without settings

    # Database
    try:
        from .store import processed_count
        processed_count()
    except Exception as e:
        failures.append(f"database: {e}")

    return failures


def main() -> None:
    failures = check()
    if failures:
        for f in failures:
            print(f"UNHEALTHY: {f}", file=sys.stderr)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
