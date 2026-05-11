"""OpenAI LLM via langchain-openai. Uses ChatOpenAI with structured output for triage + drafting."""
from __future__ import annotations

import logging
import re

from langchain_openai import ChatOpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .config import settings
from .schemas import DraftReply, Email, TriageCategory, TriageDecision

logger = logging.getLogger(__name__)

TRIAGE_SYSTEM = """You are an email triage assistant for {user}.
Classify the incoming email and decide what action is needed. Use all available signals:
- If the user is CC'd (not TO), they rarely need to act — prefer "fyi"
- Attachments like PDFs/contracts/invoices raise priority and may require action
- Automated senders (no-reply, notifications, receipts) go in "newsletter" or "fyi"
- Be conservative: only label "reply_needed" if a real person expects a response
Return your decision including a confidence score 0.0-1.0. Use <0.7 when ambiguous."""

DRAFT_SYSTEM = """You are drafting an email reply on behalf of {user}.
Write in a natural, professional but warm tone. Keep it concise — usually \
3-6 sentences unless the thread clearly demands more. Do NOT invent facts, \
commitments, dates, or details not present in the incoming email. If the user \
needs to provide information you don't have, leave a clear bracketed \
placeholder like [your availability here].

Sign off with:
{signature}
"""

COMPOSE_SYSTEM = """You are drafting a brand-new email on behalf of {user}.
Write in a natural, professional but warm tone. Keep it concise.
Do NOT invent facts or commitments — use bracketed placeholders like [details here] \
for anything you don't know.

Sign off with:
{signature}
"""

FOLLOWUP_SYSTEM = """You are writing a polite follow-up email on behalf of {user}.
The original email was sent {days} day(s) ago and has received no reply yet.
Keep it brief (2-3 sentences), friendly, and non-pushy. Do not repeat the full \
original email — just reference the topic lightly.

Sign off with:
{signature}
"""

STYLE_SYSTEM = """You are analysing a collection of emails written by {user} to learn their writing style.
Summarise in 4-6 concise bullet points:
• Typical greeting (e.g. "Hi [name]," or "Dear [name],")
• Tone (formal / semi-formal / casual)
• Average email length (very short / short / medium)
• Common phrases or patterns they use
• How they close / sign off
• Any other notable stylistic habits

Be specific — quote actual patterns from the emails where possible.
Output ONLY the bullet-point list, no preamble."""

ACTION_ACK_SYSTEM = """You are drafting a brief acknowledgement email on behalf of {user}.
The sender has asked {user} to take a non-reply action (e.g. review a document, \
pay an invoice, complete a task). Write 2-3 sentences: confirm receipt, state that \
{user} will look into it, and give a vague but realistic timeframe if appropriate. \
Do NOT commit to specific dates or details you don't have — use placeholders like \
[by end of week] if needed. Keep it professional and short.

Sign off with:
{signature}
"""


_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), "[SSN]"),
    (re.compile(r'\b(?:\d{4}[\s\-]?){3}\d{4}\b'), "[CC_NUMBER]"),
    (re.compile(r'\b(\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b'), "[PHONE]"),
]


def scrub_pii(text: str) -> str:
    for pattern, placeholder in _PII_PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


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

    sender_domain = (
        email.from_addr.split("@")[-1].rstrip(">").strip()
        if "@" in email.from_addr else "unknown"
    )
    # Determine if user is direct recipient or CC'd
    user_lower = settings.user_name.lower()
    is_direct = any(user_lower in addr.lower() for addr in email.to)
    recipient_type = "TO (direct recipient)" if is_direct else "CC (copied)"
    attachment_line = (
        f"Attachments: {', '.join(email.attachments)}"
        if email.attachments else "No attachments"
    )

    prompt = [
        ("system", TRIAGE_SYSTEM.format(user=settings.user_name)),
        (
            "human",
            f"From: {email.from_addr}\n"
            f"To: {', '.join(email.to)}\n"
            f"CC: {', '.join(email.cc) if email.cc else 'none'}\n"
            f"Recipient type: {recipient_type}\n"
            f"Sender domain: {sender_domain}\n"
            f"Date: {email.date}\n"
            f"Labels: {', '.join(email.labels)}\n"
            f"{attachment_line}\n\n"
            f"Body:\n{scrub_pii(email.body[:4000])}",
        ),
    ]
    return model.invoke(prompt)


def _style_kb_suffix(style_profile: str | None, kb_context: str | None) -> str:
    parts = []
    if style_profile:
        parts.append(f"\n\nUser's writing style:\n{style_profile}")
    if kb_context:
        parts.append(f"\n\nKnowledge base context:\n{kb_context}")
    return "".join(parts)


@_retry
def draft_reply(
    email: Email,
    triage_reasoning: str,
    category: TriageCategory | None = None,
    style_profile: str | None = None,
    kb_context: str | None = None,
) -> DraftReply:
    """Generate a reply draft for an email."""
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
            ) + _style_kb_suffix(style_profile, kb_context),
        ),
        (
            "human",
            f"Triage reasoning: {triage_reasoning}\n\n"
            f"Incoming email:\n"
            f"From: {email.from_addr}\n"
            f"Subject: {email.subject}\n\n"
            f"{scrub_pii(email.body[:4000])}"
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


@_retry
def compose_email(
    to: str,
    subject: str,
    context: str,
    style_profile: str | None = None,
    kb_context: str | None = None,
) -> DraftReply:
    """Generate a brand-new email from a brief context description."""
    model = _llm(temperature=0.4)
    prompt = [
        (
            "system",
            COMPOSE_SYSTEM.format(
                user=settings.user_name, signature=settings.user_signature
            ) + _style_kb_suffix(style_profile, kb_context),
        ),
        (
            "human",
            f"To: {to}\nSubject: {subject}\nNotes: {context}\n\nWrite the email body only.",
        ),
    ]
    logger.debug("Calling LLM to compose — %r", subject)
    response = model.invoke(prompt)
    body = response.content if isinstance(response.content, str) else str(response.content)
    return DraftReply(to=[to], subject=subject, body=body.strip())


@_retry
def analyze_style(emails: list[Email]) -> str:
    """Analyse a sample of sent emails and return a style-profile summary."""
    model = _llm(temperature=0.0)
    samples = "\n\n---\n\n".join(
        f"Subject: {e.subject}\n\n{e.body[:1500]}"
        for e in emails[:20]
    )
    prompt = [
        ("system", STYLE_SYSTEM.format(user=settings.user_name)),
        ("human", f"Here are {len(emails[:20])} emails written by {settings.user_name}:\n\n{samples}"),
    ]
    logger.debug("Calling LLM to analyse writing style (%d emails)", len(emails))
    response = model.invoke(prompt)
    return (response.content if isinstance(response.content, str) else str(response.content)).strip()


@_retry
def generate_followup(email: Email, days: int = 3) -> DraftReply:
    """Generate a follow-up for a sent email that got no reply."""
    model = _llm(temperature=0.3)
    to = email.to[0] if email.to else ""
    subject = email.subject if email.subject.lower().startswith("re:") else f"Re: {email.subject}"
    prompt = [
        (
            "system",
            FOLLOWUP_SYSTEM.format(
                user=settings.user_name,
                signature=settings.user_signature,
                days=days,
            ),
        ),
        (
            "human",
            f"Original email:\nTo: {', '.join(email.to)}\nSubject: {email.subject}\n\n"
            f"{email.body[:2000]}\n\nWrite the follow-up body only.",
        ),
    ]
    logger.debug("Calling LLM for follow-up — %r", email.subject)
    response = model.invoke(prompt)
    body = response.content if isinstance(response.content, str) else str(response.content)
    return DraftReply(to=[to], subject=subject, body=body.strip(), thread_id=email.thread_id)
