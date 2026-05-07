"""OpenAI LLM via langchain-openai. Uses ChatOpenAI with structured output for triage + drafting."""
from __future__ import annotations

import logging

from langchain_openai import ChatOpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .config import settings
from .schemas import DraftReply, Email, TriageCategory, TriageDecision

logger = logging.getLogger(__name__)

TRIAGE_SYSTEM = """You are an email triage assistant for {user}.
Classify the incoming email and decide what action is needed. Be conservative: \
only label something "reply_needed" if the sender is a real person expecting a \
response (not automated mail). Newsletters, receipts, notifications, and \
marketing go in "newsletter" or "fyi".
Return your decision in the required structured format."""

DRAFT_SYSTEM = """You are drafting an email reply on behalf of {user}.
Write in a natural, professional but warm tone. Keep it concise — usually \
3-6 sentences unless the thread clearly demands more. Do NOT invent facts, \
commitments, dates, or details not present in the incoming email. If the user \
needs to provide information you don't have, leave a clear bracketed \
placeholder like [your availability here].

Sign off with:
{signature}
"""

ACTION_ACK_SYSTEM = """You are drafting a brief acknowledgement email on behalf of {user}.
The sender has asked {user} to take a non-reply action (e.g. review a document, \
pay an invoice, complete a task). Write 2-3 sentences: confirm receipt, state that \
{user} will look into it, and give a vague but realistic timeframe if appropriate. \
Do NOT commit to specific dates or details you don't have — use placeholders like \
[by end of week] if needed. Keep it professional and short.

Sign off with:
{signature}
"""


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ("rate limit", "timeout", "connection", "503", "502", "500", "overloaded"))


_retry = retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)


def _llm(**kwargs) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=kwargs.pop("temperature", 0.2),
        **kwargs,
    )


@_retry
def triage_email(email: Email) -> TriageDecision:
    """Run triage on a single email and return a structured decision."""
    logger.debug("Calling LLM for triage — %r", email.subject[:60])
    model = _llm(temperature=0.0).with_structured_output(TriageDecision)

    prompt = [
        ("system", TRIAGE_SYSTEM.format(user=settings.user_name)),
        (
            "human",
            f"From: {email.from_addr}\n"
            f"Subject: {email.subject}\n"
            f"Date: {email.date}\n"
            f"Labels: {', '.join(email.labels)}\n\n"
            f"Body:\n{email.body[:4000]}",
        ),
    ]
    return model.invoke(prompt)


@_retry
def draft_reply(
    email: Email,
    triage_reasoning: str,
    category: TriageCategory | None = None,
) -> DraftReply:
    """Generate a reply draft for an email.

    Uses a shorter acknowledgement prompt for action_required emails.
    """
    model = _llm(temperature=0.4)

    reply_to = email.from_addr
    subject = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"

    thread_section = ""
    if email.thread_messages:
        parts = [f"[{m.date}] {m.from_addr}:\n{m.body}" for m in email.thread_messages]
        thread_section = (
            "\n\nThread history (earliest → most recent):\n---\n"
            + "\n---\n".join(parts)
            + "\n---"
        )

    is_action = category == TriageCategory.ACTION_REQUIRED
    system_template = ACTION_ACK_SYSTEM if is_action else DRAFT_SYSTEM
    instruction = (
        "Write a short acknowledgement only (no subject line, no 'To:' header)."
        if is_action
        else "Write the body of the reply only (no subject line, no 'To:' header)."
    )

    prompt = [
        (
            "system",
            system_template.format(
                user=settings.user_name, signature=settings.user_signature
            ),
        ),
        (
            "human",
            f"Triage reasoning: {triage_reasoning}\n\n"
            f"Incoming email:\n"
            f"From: {email.from_addr}\n"
            f"Subject: {email.subject}\n\n"
            f"{email.body[:4000]}"
            f"{thread_section}\n\n"
            f"{instruction}",
        ),
    ]
    logger.debug("Calling LLM for draft — %r", email.subject[:60])
    response = model.invoke(prompt)
    body = response.content if isinstance(response.content, str) else str(response.content)

    return DraftReply(
        to=[reply_to],
        subject=subject,
        body=body.strip(),
        in_reply_to_id=email.id,
        thread_id=email.thread_id,
    )
