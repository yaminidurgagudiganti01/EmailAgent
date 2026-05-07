"""LangGraph state machine for the email agent.

Flow:
    fetch_emails -> triage_all -> draft_replies -> save_drafts -> END

We process the inbox as a batch: fetch N emails, skip already-processed ones,
triage each, then draft replies only for actionable categories. Finally, save
every draft to Gmail Drafts and mark emails as processed (nothing is sent).
"""
from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .gmail_client import fetch_emails, save_draft
from .llm import draft_reply, triage_email
from .schemas import Email, ProcessedEmail, TriageCategory
from .store import is_processed, mark_processed

logger = logging.getLogger(__name__)

# Categories we generate drafts for.
DRAFT_CATEGORIES = {
    TriageCategory.REPLY_NEEDED,
    TriageCategory.MEETING,
    TriageCategory.ACTION_REQUIRED,
}


class AgentState(TypedDict):
    """Graph state — TypedDict is preferred over Pydantic in LangGraph 1.1+."""

    query: str
    max_emails: int
    emails: list[Email]
    processed: list[ProcessedEmail]
    saved_draft_ids: list[str]


# --- Nodes ---


def node_fetch(state: AgentState) -> dict:
    logger.info("Fetching emails — query=%r", state["query"])
    emails = fetch_emails(query=state["query"], max_results=state["max_emails"])

    fresh = [e for e in emails if not is_processed(e.id)]
    skipped = len(emails) - len(fresh)
    if skipped:
        logger.info("Skipping %d already-processed email(s)", skipped)
    logger.info("%d new email(s) to process", len(fresh))

    return {"emails": fresh, "processed": [], "saved_draft_ids": []}


def node_triage(state: AgentState) -> dict:
    processed: list[ProcessedEmail] = []
    total = len(state["emails"])
    for i, email in enumerate(state["emails"], 1):
        logger.info("Triaging %d/%d — %r", i, total, email.subject[:60])
        try:
            decision = triage_email(email)
            logger.info(
                "  → %s (%s) — %s", decision.category.value, decision.priority, decision.reasoning
            )
            processed.append(ProcessedEmail(email=email, triage=decision))
        except Exception as e:  # noqa: BLE001
            logger.error("Triage failed for %r: %s", email.subject[:60], e)
            continue
    return {"processed": processed}


def node_draft(state: AgentState) -> dict:
    updated: list[ProcessedEmail] = []
    for pe in state["processed"]:
        if pe.triage.category not in DRAFT_CATEGORIES:
            updated.append(pe)
            continue

        logger.info("Drafting reply — %r", pe.email.subject[:60])
        try:
            draft = draft_reply(pe.email, pe.triage.reasoning, category=pe.triage.category)
            updated.append(pe.model_copy(update={"draft": draft}))
            logger.debug("Draft ready (%d chars)", len(draft.body))
        except Exception as e:  # noqa: BLE001
            logger.error("Draft failed for %r: %s", pe.email.subject[:60], e)
            updated.append(pe.model_copy(update={"error": str(e)}))
    return {"processed": updated}


def node_save(state: AgentState) -> dict:
    saved: list[str] = []
    for pe in state["processed"]:
        if pe.draft is None:
            mark_processed(pe.email.id, None)
            continue
        try:
            draft_id = save_draft(pe.draft)
            saved.append(draft_id)
            mark_processed(pe.email.id, draft_id)
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Save failed for %r: %s — will retry next run", pe.draft.subject[:60], e
            )
    return {"saved_draft_ids": saved}


# --- Graph ---


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("fetch", node_fetch)
    g.add_node("triage", node_triage)
    g.add_node("draft", node_draft)
    g.add_node("save", node_save)

    g.add_edge(START, "fetch")
    g.add_edge("fetch", "triage")
    g.add_edge("triage", "draft")
    g.add_edge("draft", "save")
    g.add_edge("save", END)
    return g.compile()


graph = build_graph()
