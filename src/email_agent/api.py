"""FastAPI backend — exposes all agent capabilities as a REST API."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import settings
from .gmail_client import apply_label, fetch_emails, fetch_sent_no_reply, fetch_sent_sample, save_draft, send_email
from .llm import analyze_style, compose_email, draft_reply, generate_followup, triage_email
from .schemas import DraftReply, TriageCategory
from .store import (
    add_exclude_rule,
    add_kb_entry,
    delete_kb_entry,
    get_email_log,
    get_exclude_rules,
    get_kb,
    get_style_profile,
    has_followup_draft,
    is_excluded,
    log_email,
    mark_processed,
    mark_sent,
    processed_count,
    record_followup_draft,
    remove_exclude_rule,
    save_style_profile,
    sent_count,
    update_followup_status,
    update_log_sent,
)

logger = logging.getLogger(__name__)

# Max concurrent LLM calls per /run
_SEM = asyncio.Semaphore(5)

DRAFT_CATEGORIES = {
    TriageCategory.REPLY_NEEDED,
    TriageCategory.MEETING,
    TriageCategory.ACTION_REQUIRED,
}


# ── Scheduler ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.schedule_interval_minutes > 0:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _scheduled_run,
            "interval",
            minutes=settings.schedule_interval_minutes,
            id="inbox_run",
        )
        scheduler.start()
        logger.info("Scheduler started — inbox run every %d min", settings.schedule_interval_minutes)
        yield
        scheduler.shutdown()
    else:
        yield


app = FastAPI(title="Email Agent API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request models ────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    query: str = settings.inbox_query
    max_emails: int = settings.max_emails_per_run
    apply_labels: bool = True
    mark_as_read: bool = False


class SendRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    cc: list[str] = []
    thread_id: str | None = None
    email_id: str | None = None


class ComposeRequest(BaseModel):
    to: str
    subject: str
    context: str


class RuleRequest(BaseModel):
    rule_type: str   # "sender" | "domain" | "category"
    value: str


class FollowupRequest(BaseModel):
    days: int = 3
    max_emails: int = 10


class FollowupDraftRequest(BaseModel):
    email_id: str
    to: list[str]
    subject: str
    snippet: str
    thread_id: str | None = None
    days: int = 3


class FollowupStatusRequest(BaseModel):
    status: str  # "sent" | "dismissed"


class KbRequest(BaseModel):
    title: str
    content: str


# ── Core pipeline ─────────────────────────────────────────────────────────────

async def _process_one(
    email,
    rules: list[dict],
    style_profile: str | None,
    kb_context: str | None,
    apply_labels: bool,
    mark_as_read: bool,
) -> dict[str, Any]:
    """Triage and optionally draft a reply for a single email."""
    async with _SEM:
        try:
            decision = await asyncio.to_thread(triage_email, email)
        except Exception as e:
            logger.error("Triage failed for %s: %s", email.id, e)
            return {"email_id": email.id, "subject": email.subject, "error": str(e)}

        skip_draft = is_excluded(email.from_addr, decision.category.value, rules)
        needs_review = decision.confidence < settings.confidence_threshold

        draft_data: dict | None = None
        draft_id: str | None = None

        if not skip_draft and not needs_review and decision.category in DRAFT_CATEGORIES:
            try:
                draft = await asyncio.to_thread(
                    draft_reply, email, decision.reasoning,
                    decision.category, style_profile, kb_context,
                )
                draft_data = {
                    "to": draft.to,
                    "cc": draft.cc,
                    "subject": draft.subject,
                    "body": draft.body,
                    "thread_id": draft.thread_id,
                }
            except Exception as e:
                logger.error("Draft failed for %s: %s", email.id, e)

        if apply_labels:
            try:
                await asyncio.to_thread(apply_label, email.id, decision.category.value)
            except Exception as e:
                logger.warning("Label failed for %s: %s", email.id, e)

        if mark_as_read:
            try:
                from .gmail_client import _get_service
                svc = await asyncio.to_thread(_get_service)
                svc.users().messages().modify(
                    userId="me", id=email.id, body={"removeLabelIds": ["UNREAD"]}
                ).execute()
            except Exception:
                pass

        log_email(
            email_id=email.id,
            from_addr=email.from_addr,
            subject=email.subject,
            category=decision.category.value,
            priority=decision.priority,
            draft_id=draft_id,
        )

        return {
            "email_id":       email.id,
            "from_addr":      email.from_addr,
            "subject":        email.subject,
            "date":           email.date,
            "snippet":        email.snippet,
            "category":       decision.category.value,
            "priority":       decision.priority,
            "confidence":     decision.confidence,
            "needs_review":   needs_review,
            "reasoning":      decision.reasoning,
            "suggested_action": decision.suggested_action,
            "excluded":       skip_draft,
            "draft":          draft_data,
        }


async def _run_inbox(
    query: str, max_emails: int, apply_labels: bool, mark_as_read: bool
) -> dict[str, Any]:
    rules         = get_exclude_rules()
    style_profile = get_style_profile()
    kb_entries    = get_kb()
    kb_context    = "\n\n".join(f"### {e['title']}\n{e['content']}" for e in kb_entries) or None
    emails        = await asyncio.to_thread(fetch_emails, query=query, max_results=max_emails)

    results = await asyncio.gather(
        *[_process_one(e, rules, style_profile, kb_context, apply_labels, mark_as_read)
          for e in emails],
        return_exceptions=True,
    )
    # Convert any unhandled exceptions into error entries instead of crashing
    safe = []
    for r in results:
        if isinstance(r, Exception):
            logger.error("Unhandled error in _process_one: %s", r)
            safe.append({"error": str(r)})
        else:
            safe.append(r)
    return {"count": len(safe), "emails": safe}


async def _scheduled_run() -> None:
    logger.info("Scheduled inbox run starting")
    try:
        await _run_inbox(settings.inbox_query, settings.max_emails_per_run, True, False)
        logger.info("Scheduled inbox run complete")
    except Exception as e:
        logger.error("Scheduled run failed: %s", e)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": settings.openai_model,
        "scheduler": (
            f"every {settings.schedule_interval_minutes}min"
            if settings.schedule_interval_minutes > 0 else "off"
        ),
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats() -> dict:
    return {"processed": processed_count(), "sent": sent_count()}


# ── Run pipeline ──────────────────────────────────────────────────────────────

@app.post("/run")
async def run_pipeline(req: RunRequest) -> dict[str, Any]:
    try:
        return await _run_inbox(req.query, req.max_emails, req.apply_labels, req.mark_as_read)
    except Exception as e:
        logger.exception("Pipeline failed")
        raise HTTPException(status_code=500, detail=str(e))


# ── Save draft ────────────────────────────────────────────────────────────────

@app.post("/drafts/save")
def api_save_draft(req: SendRequest) -> dict:
    draft = DraftReply(
        to=req.to, cc=req.cc, subject=req.subject,
        body=req.body, thread_id=req.thread_id,
    )
    try:
        draft_id = save_draft(draft)
        if req.email_id:
            mark_processed(req.email_id, draft_id)
        return {"draft_id": draft_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Send email ────────────────────────────────────────────────────────────────

@app.post("/emails/send")
def api_send_email(req: SendRequest) -> dict:
    draft = DraftReply(
        to=req.to, cc=req.cc, subject=req.subject,
        body=req.body, thread_id=req.thread_id,
    )
    try:
        msg_id = send_email(draft)
        mark_sent(msg_id, req.email_id, req.subject, ", ".join(req.to))
        if req.email_id:
            mark_processed(req.email_id, msg_id)
            update_log_sent(req.email_id)
        else:
            log_email(
                email_id=msg_id,
                from_addr="me",
                subject=req.subject,
                category="compose",
                priority="medium",
                draft_id=None,
                sent=True,
            )
        return {"message_id": msg_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Compose ───────────────────────────────────────────────────────────────────

@app.post("/compose")
def api_compose(req: ComposeRequest) -> dict:
    try:
        style_profile = get_style_profile()
        kb_entries    = get_kb()
        kb_context    = "\n\n".join(f"### {e['title']}\n{e['content']}" for e in kb_entries) or None
        draft = compose_email(
            to=req.to, subject=req.subject, context=req.context,
            style_profile=style_profile, kb_context=kb_context,
        )
        return {"to": draft.to, "subject": draft.subject, "body": draft.body}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Follow-ups ────────────────────────────────────────────────────────────────

@app.post("/followups/scan")
def api_scan_followups(req: FollowupRequest) -> dict:
    emails = fetch_sent_no_reply(days=req.days, max_results=req.max_emails)
    # Filter threads already tracked to avoid duplicate nudges
    candidates = [e for e in emails if not has_followup_draft(e.thread_id)]
    return {
        "count": len(candidates),
        "emails": [
            {
                "email_id": e.id,
                "to":       e.to,
                "subject":  e.subject,
                "date":     e.date,
                "snippet":  e.snippet,
                "thread_id": e.thread_id,
            }
            for e in candidates
        ],
    }


@app.post("/followups/draft")
def api_followup_draft(req: FollowupDraftRequest) -> dict:
    thread_id = req.thread_id or req.email_id

    if has_followup_draft(thread_id):
        raise HTTPException(
            status_code=409,
            detail="A follow-up draft already exists for this thread. Send or dismiss it first.",
        )

    from .schemas import Email as EmailSchema
    stub = EmailSchema(
        id=req.email_id,
        thread_id=thread_id,
        from_addr="me",
        to=req.to,
        subject=req.subject,
        snippet=req.snippet,
        body=req.snippet,
    )
    draft = generate_followup(stub, days=req.days)
    record_followup_draft(thread_id, req.email_id)

    return {
        "to":        draft.to,
        "subject":   draft.subject,
        "body":      draft.body,
        "thread_id": draft.thread_id,
    }


@app.patch("/followups/{thread_id}")
def api_update_followup(thread_id: str, req: FollowupStatusRequest) -> dict:
    if req.status not in ("sent", "dismissed"):
        raise HTTPException(status_code=400, detail="status must be 'sent' or 'dismissed'")
    update_followup_status(thread_id, req.status)
    return {"ok": True}


# ── Conversations ─────────────────────────────────────────────────────────────

@app.get("/conversations")
def api_conversations(limit: int = 100) -> dict:
    return {"entries": get_email_log(limit=limit)}


# ── Exclude rules ─────────────────────────────────────────────────────────────

@app.get("/rules")
def api_get_rules() -> dict:
    return {"rules": get_exclude_rules()}


@app.post("/rules")
def api_add_rule(req: RuleRequest) -> dict:
    if req.rule_type not in ("sender", "domain", "category"):
        raise HTTPException(status_code=400, detail="rule_type must be sender, domain, or category")
    add_exclude_rule(req.rule_type, req.value)
    return {"ok": True}


@app.delete("/rules/{rule_id}")
def api_delete_rule(rule_id: int) -> dict:
    remove_exclude_rule(rule_id)
    return {"ok": True}


# ── Style learning ────────────────────────────────────────────────────────────

@app.get("/style")
def api_get_style() -> dict:
    return {"profile": get_style_profile()}


@app.post("/style/learn")
def api_learn_style() -> dict:
    try:
        emails = fetch_sent_sample()
        if not emails:
            raise HTTPException(status_code=404, detail="No sent emails found to analyse")
        profile = analyze_style(emails)
        save_style_profile(profile)
        return {"profile": profile, "emails_analysed": len(emails)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Knowledge base ────────────────────────────────────────────────────────────

@app.get("/kb")
def api_get_kb() -> dict:
    return {"entries": get_kb()}


@app.post("/kb")
def api_add_kb(req: KbRequest) -> dict:
    if not req.title.strip() or not req.content.strip():
        raise HTTPException(status_code=400, detail="title and content are required")
    add_kb_entry(req.title.strip(), req.content.strip())
    return {"ok": True}


@app.delete("/kb/{entry_id}")
def api_delete_kb(entry_id: int) -> dict:
    delete_kb_entry(entry_id)
    return {"ok": True}
