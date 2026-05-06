"""Smoke test: verify the graph compiles and the schemas validate."""
from __future__ import annotations

from email_agent.agent import build_graph
from email_agent.schemas import (
    DraftReply,
    Email,
    ProcessedEmail,
    TriageCategory,
    TriageDecision,
)


def test_graph_compiles():
    graph = build_graph()
    assert graph is not None
    # Should have our 4 nodes plus START/END
    node_names = set(graph.get_graph().nodes.keys())
    assert {"fetch", "triage", "draft", "save"}.issubset(node_names)


def test_email_schema():
    email = Email(
        id="abc",
        thread_id="t1",
        from_addr="alice@example.com",
        subject="Hi",
        body="Want to grab coffee Thursday?",
    )
    assert email.from_addr == "alice@example.com"
    assert email.labels == []


def test_triage_schema():
    decision = TriageDecision(
        category=TriageCategory.REPLY_NEEDED,
        priority="medium",
        reasoning="Personal invitation from known contact.",
        suggested_action="Draft a reply confirming or proposing a time.",
    )
    assert decision.category == TriageCategory.REPLY_NEEDED


def test_processed_email_with_draft():
    email = Email(id="1", thread_id="t1", from_addr="a@b.com", subject="s", body="b")
    triage = TriageDecision(
        category=TriageCategory.FYI,
        priority="low",
        reasoning="r",
        suggested_action="a",
    )
    draft = DraftReply(to=["a@b.com"], subject="Re: s", body="ok")
    pe = ProcessedEmail(email=email, triage=triage, draft=draft)
    assert pe.draft is not None
