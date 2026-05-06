"""Typed models for emails, triage decisions, and drafts."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ThreadMessage(BaseModel):
    """A previous message in the same thread, for draft context."""

    from_addr: str
    date: str
    body: str


class Email(BaseModel):
    """A single email message fetched from Gmail."""

    id: str
    thread_id: str
    from_addr: str
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str = ""
    snippet: str = ""
    body: str = ""
    date: str = ""
    labels: list[str] = Field(default_factory=list)
    thread_messages: list[ThreadMessage] = Field(default_factory=list)


class TriageCategory(str, Enum):
    REPLY_NEEDED = "reply_needed"       # Personal / important, user should reply
    FYI = "fyi"                         # No reply needed, just informational
    MEETING = "meeting"                 # Meeting invite or scheduling
    ACTION_REQUIRED = "action_required" # Non-reply action (pay bill, review doc, etc.)
    NEWSLETTER = "newsletter"           # Newsletter / marketing / automated
    SPAM = "spam"                       # Junk


class TriageDecision(BaseModel):
    """Structured triage output from the LLM."""

    category: TriageCategory
    priority: Literal["high", "medium", "low"]
    reasoning: str = Field(description="One-sentence justification.")
    suggested_action: str = Field(
        description="What the user should do (e.g. 'draft a reply declining').",
    )


class DraftReply(BaseModel):
    """A generated email draft."""

    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    in_reply_to_id: str | None = None
    thread_id: str | None = None


class ProcessedEmail(BaseModel):
    """An email after it's been through triage (and optionally drafted)."""

    email: Email
    triage: TriageDecision
    draft: DraftReply | None = None
    error: str | None = None
