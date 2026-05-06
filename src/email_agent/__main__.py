"""CLI entry point. Run:

    python -m email_agent              # process inbox, save all drafts automatically
    python -m email_agent --approve    # review + approve each draft before saving
    python -m email_agent --dry-run    # triage + draft but don't save anything
    python -m email_agent --query "from:boss@example.com" --max 5
"""
from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import settings
from .log import setup_logging

# Logging must be configured before any other local import that might log at import time.
setup_logging(log_dir=settings.log_dir)

from .agent import build_graph, node_draft, node_fetch, node_triage  # noqa: E402
from .gmail_client import save_draft                                  # noqa: E402
from .store import mark_processed                                     # noqa: E402

logger = logging.getLogger(__name__)
console = Console()


def _approve_loop(state: dict) -> list[str]:
    """Interactively approve drafts one by one. Returns saved draft IDs."""
    drafts = [(i, pe) for i, pe in enumerate(state["processed"]) if pe.draft]

    if not drafts:
        console.print("[yellow]No drafts to review.[/yellow]")
        # Still mark non-draft emails as processed.
        for pe in state["processed"]:
            mark_processed(pe.email.id)
        return []

    console.print(f"\n[bold]{len(drafts)} draft(s) to review[/bold]  —  [A]ccept · [S]kip\n")
    saved: list[str] = []
    reviewed_ids: set[str] = set()

    for num, (_, pe) in enumerate(drafts, 1):
        console.rule(f"[bold]Draft {num}/{len(drafts)}[/bold]")
        console.print(f"[cyan]From:[/cyan]     {pe.email.from_addr}")
        console.print(f"[cyan]Subject:[/cyan]  {pe.email.subject}")
        console.print(f"[cyan]Category:[/cyan] {pe.triage.category.value} ({pe.triage.priority})")
        console.print(f"[dim]{pe.triage.reasoning}[/dim]\n")
        console.print(Panel(pe.draft.body, title="Draft body", border_style="green"))

        while True:
            raw = console.input("\n[bold]Action[/bold] \\[A/s]: ").strip().lower()
            choice = raw or "a"
            if choice == "a":
                try:
                    draft_id = save_draft(pe.draft)
                    saved.append(draft_id)
                    mark_processed(pe.email.id, draft_id)
                    reviewed_ids.add(pe.email.id)
                    console.print(f"[green]✓ Saved[/green] ({draft_id[:8]}…)\n")
                    logger.info("Approved and saved draft %s for email %s", draft_id, pe.email.id)
                except Exception as e:  # noqa: BLE001
                    console.print(f"[red]Save failed: {e}[/red]\n")
                    logger.error("Save failed for %s: %s", pe.email.id, e)
                break
            elif choice == "s":
                mark_processed(pe.email.id)
                reviewed_ids.add(pe.email.id)
                console.print("[dim]Skipped.[/dim]\n")
                logger.info("Skipped draft for email %s", pe.email.id)
                break
            else:
                console.print("[red]Enter A to accept or S to skip.[/red]")

    # Mark any non-drafted emails as processed too.
    for pe in state["processed"]:
        if pe.email.id not in reviewed_ids:
            mark_processed(pe.email.id)

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAI email triage + drafting agent")
    parser.add_argument("--query", default=settings.inbox_query, help="Gmail search query")
    parser.add_argument("--max", type=int, default=settings.max_emails_per_run)
    parser.add_argument("--dry-run", action="store_true", help="Triage + draft but don't save")
    parser.add_argument("--approve", action="store_true", help="Review each draft before saving")
    args = parser.parse_args()

    try:
        settings.validate()
    except ValueError as e:
        console.print(f"[bold red]Startup error:[/bold red]\n{e}")
        raise SystemExit(1)

    logger.info("Email Agent starting — model=%s", settings.openai_model)
    console.rule(f"[bold]Email Agent[/bold] — model={settings.openai_model}")

    initial = {
        "query": args.query,
        "max_emails": args.max,
        "emails": [],
        "processed": [],
        "saved_draft_ids": [],
    }

    if args.dry_run or args.approve:
        state = initial
        for fn in (node_fetch, node_triage, node_draft):
            state = {**state, **fn(state)}
    else:
        state = build_graph().invoke(initial)

    # Summary table
    table = Table(title="Triage Summary", show_lines=False)
    table.add_column("From", style="cyan", max_width=32)
    table.add_column("Subject", max_width=50)
    table.add_column("Category")
    table.add_column("Priority")
    table.add_column("Drafted?", justify="center")

    for pe in state["processed"]:
        table.add_row(
            pe.email.from_addr[:30],
            pe.email.subject[:48],
            pe.triage.category.value,
            pe.triage.priority,
            "✓" if pe.draft else "—",
        )

    console.print(table)

    if args.approve:
        saved_ids = _approve_loop(state)
        console.print(f"\n[bold green]Saved {len(saved_ids)} draft(s) to Gmail.[/bold green]")
        logger.info("Approve run complete — %d draft(s) saved", len(saved_ids))
    elif args.dry_run:
        console.print("\n[dim]Dry run — nothing saved.[/dim]")
        logger.info("Dry run complete")
    else:
        n = len(state["saved_draft_ids"])
        console.print(f"\n[bold green]Saved {n} draft(s) to Gmail.[/bold green]")
        logger.info("Run complete — %d draft(s) saved", n)


if __name__ == "__main__":
    main()
