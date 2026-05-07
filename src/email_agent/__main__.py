"""CLI entry point.

    python -m email_agent                    # triage + save all drafts
    python -m email_agent --approve          # review each draft: [A]draft [S]kip [E]send
    python -m email_agent --dry-run          # triage only, save nothing
    python -m email_agent --compose          # compose a brand-new email with AI
    python -m email_agent --followup         # find sent emails with no reply and draft follow-ups
    python -m email_agent --query "..." --max 5
"""
from __future__ import annotations

import argparse
import logging

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from .config import settings
from .log import setup_logging

setup_logging(log_dir=settings.log_dir, fmt=settings.log_format)

from .agent import build_graph, node_draft, node_fetch, node_triage  # noqa: E402
from .gmail_client import (                                           # noqa: E402
    fetch_sent_no_reply,
    save_draft,
    send_email,
)
from .llm import compose_email, draft_reply, generate_followup        # noqa: E402
from .store import mark_processed, mark_sent                          # noqa: E402

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Approve loop  (triage + draft + interactive review)
# ---------------------------------------------------------------------------

def _approve_loop(state: dict) -> list[str]:
    """Review each draft: [A] save to Gmail Drafts  [S] skip  [E] send now."""
    drafts = [(i, pe) for i, pe in enumerate(state["processed"]) if pe.draft]

    if not drafts:
        console.print("[yellow]No drafts to review.[/yellow]")
        for pe in state["processed"]:
            mark_processed(pe.email.id)
        return []

    console.print(
        f"\n[bold]{len(drafts)} draft(s) to review[/bold]  —  "
        "[A]ccept draft · [S]kip · [E]send now\n"
    )
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
            choice = Prompt.ask("\n[bold]Action[/bold]", choices=["a", "s", "e"], default="a")
            if choice == "a":
                try:
                    draft_id = save_draft(pe.draft)
                    saved.append(draft_id)
                    mark_processed(pe.email.id, draft_id)
                    reviewed_ids.add(pe.email.id)
                    console.print(f"[green]✓ Saved to Drafts[/green] ({draft_id[:8]}…)\n")
                    logger.info("Saved draft %s for email %s", draft_id, pe.email.id)
                except Exception as e:  # noqa: BLE001
                    console.print(f"[red]Save failed: {e}[/red]\n")
                break
            elif choice == "e":
                console.print(
                    "[bold yellow]⚠ This will SEND the email immediately. Are you sure?[/bold yellow]"
                )
                confirm = Prompt.ask("Confirm send", choices=["yes", "no"], default="no")
                if confirm == "yes":
                    try:
                        msg_id = send_email(pe.draft)
                        mark_sent(
                            msg_id,
                            pe.email.id,
                            pe.draft.subject,
                            ", ".join(pe.draft.to),
                        )
                        mark_processed(pe.email.id, msg_id)
                        reviewed_ids.add(pe.email.id)
                        console.print(f"[bold green]✓ Sent[/bold green] ({msg_id[:8]}…)\n")
                        logger.info("Sent email %s for email %s", msg_id, pe.email.id)
                    except Exception as e:  # noqa: BLE001
                        console.print(f"[red]Send failed: {e}[/red]\n")
                    break
            elif choice == "s":
                mark_processed(pe.email.id)
                reviewed_ids.add(pe.email.id)
                console.print("[dim]Skipped.[/dim]\n")
                break

    for pe in state["processed"]:
        if pe.email.id not in reviewed_ids:
            mark_processed(pe.email.id)

    return saved


# ---------------------------------------------------------------------------
# Compose  (brand-new email)
# ---------------------------------------------------------------------------

def _compose_flow() -> None:
    console.rule("[bold]Compose new email[/bold]")
    to = Prompt.ask("[cyan]To[/cyan]")
    subject = Prompt.ask("[cyan]Subject[/cyan]")
    context = Prompt.ask("[cyan]Notes / context[/cyan] (what should the email say?)")

    console.print("\n[dim]Generating draft…[/dim]")
    try:
        draft = compose_email(to=to, subject=subject, context=context)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]LLM error: {e}[/red]")
        return

    console.print(Panel(draft.body, title=f"To: {to} | Subject: {subject}", border_style="blue"))

    choice = Prompt.ask("[bold]Action[/bold]", choices=["a", "e", "q"], default="a",
                        show_choices=True)
    # a=save draft, e=send now, q=quit
    if choice == "a":
        try:
            draft_id = save_draft(draft)
            console.print(f"[green]✓ Saved to Drafts[/green] ({draft_id[:8]}…)")
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]Save failed: {e}[/red]")
    elif choice == "e":
        confirm = Prompt.ask("Send now? [yes/no]", choices=["yes", "no"], default="no")
        if confirm == "yes":
            try:
                msg_id = send_email(draft)
                mark_sent(msg_id, None, draft.subject, to)
                console.print(f"[bold green]✓ Sent[/bold green] ({msg_id[:8]}…)")
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]Send failed: {e}[/red]")
    else:
        console.print("[dim]Discarded.[/dim]")


# ---------------------------------------------------------------------------
# Follow-up  (sent emails with no reply)
# ---------------------------------------------------------------------------

def _followup_flow(days: int, max_emails: int) -> None:
    console.rule(f"[bold]Follow-up check[/bold] — sent >{days}d ago, no reply")
    console.print("[dim]Fetching sent emails…[/dim]")

    try:
        emails = fetch_sent_no_reply(days=days, max_results=max_emails)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Fetch failed: {e}[/red]")
        return

    if not emails:
        console.print("[green]No follow-ups needed — all sent emails have replies.[/green]")
        return

    console.print(f"[yellow]{len(emails)} email(s) need a follow-up[/yellow]\n")

    for i, email in enumerate(emails, 1):
        console.rule(f"Follow-up {i}/{len(emails)}")
        console.print(f"[cyan]To:[/cyan]      {', '.join(email.to)}")
        console.print(f"[cyan]Subject:[/cyan] {email.subject}")
        console.print(f"[cyan]Sent:[/cyan]    {email.date[:24]}")

        draft = generate_followup(email, days=days)
        console.print(Panel(draft.body, title="Follow-up draft", border_style="yellow"))

        choice = Prompt.ask("[bold]Action[/bold]", choices=["a", "e", "s"], default="a")
        if choice == "a":
            try:
                draft_id = save_draft(draft)
                console.print(f"[green]✓ Saved to Drafts[/green] ({draft_id[:8]}…)\n")
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]Save failed: {e}[/red]\n")
        elif choice == "e":
            confirm = Prompt.ask("Send now? [yes/no]", choices=["yes", "no"], default="no")
            if confirm == "yes":
                try:
                    msg_id = send_email(draft)
                    mark_sent(msg_id, email.id, draft.subject, ", ".join(draft.to))
                    console.print(f"[bold green]✓ Sent[/bold green] ({msg_id[:8]}…)\n")
                except Exception as e:  # noqa: BLE001
                    console.print(f"[red]Send failed: {e}[/red]\n")
        else:
            console.print("[dim]Skipped.[/dim]\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Email Agent — triage, draft, compose, send")
    parser.add_argument("--query", default=settings.inbox_query)
    parser.add_argument("--max", type=int, default=settings.max_emails_per_run)
    parser.add_argument("--dry-run", action="store_true", help="Triage + draft, save nothing")
    parser.add_argument("--approve", action="store_true",
                        help="Review each draft: [A]save [S]kip [E]send")
    parser.add_argument("--compose", action="store_true", help="Compose a new email with AI")
    parser.add_argument("--followup", action="store_true",
                        help="Find sent emails with no reply and draft follow-ups")
    parser.add_argument("--days", type=int, default=3,
                        help="Days threshold for follow-up detection (default: 3)")
    args = parser.parse_args()

    try:
        settings.validate()
    except ValueError as e:
        console.print(f"[bold red]Startup error:[/bold red]\n{e}")
        raise SystemExit(1)

    logger.info("Email Agent starting — model=%s", settings.openai_model)

    # ── Compose mode ──────────────────────────────────────────────────────────
    if args.compose:
        _compose_flow()
        return

    # ── Follow-up mode ────────────────────────────────────────────────────────
    if args.followup:
        _followup_flow(days=args.days, max_emails=args.max)
        return

    # ── Triage mode ───────────────────────────────────────────────────────────
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
        console.print(f"\n[bold green]Done — {len(saved_ids)} draft(s) saved.[/bold green]")
    elif args.dry_run:
        console.print("\n[dim]Dry run — nothing saved.[/dim]")
    else:
        n = len(state["saved_draft_ids"])
        console.print(f"\n[bold green]Saved {n} draft(s) to Gmail.[/bold green]")


if __name__ == "__main__":
    main()
