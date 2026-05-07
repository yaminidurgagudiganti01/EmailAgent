"""FastAPI backend — exposes all agent capabilities as a REST API."""
from __future__ import annotations

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
    is_excluded,
    log_email,
    mark_processed,
    mark_sent,
    processed_count,
    remove_exclude_rule,
    save_style_profile,
    sent_count,
    update_log_sent,
)

app = FastAPI(title="Email Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://*.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DRAFT_CATEGORIES = {
    TriageCategory.REPLY_NEEDED,
    TriageCategory.MEETING,
    TriageCategory.ACTION_REQUIRED,
}


# ── Models ────────────────────────────────────────────────────────────────────

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


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.openai_model}


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats")
def stats() -> dict:
    return {
        "processed": processed_count(),
        "sent": sent_count(),
    }


# ── Run pipeline ──────────────────────────────────────────────────────────────

@app.post("/run")
def run_pipeline(req: RunRequest) -> dict[str, Any]:
    rules         = get_exclude_rules()
    style_profile = get_style_profile()
    kb_entries    = get_kb()
    kb_context    = "\n\n".join(f"### {e['title']}\n{e['content']}" for e in kb_entries) or None
    emails        = fetch_emails(query=req.query, max_results=req.max_emails)

    results = []
    for email in emails:
        # Exclude rules check
        skip_draft = False
        decision = triage_email(email)

        if is_excluded(email.from_addr, decision.category.value, rules):
            skip_draft = True

        draft_id: str | None = None
        draft_data: dict | None = None

        if not skip_draft and decision.category in DRAFT_CATEGORIES:
            draft = draft_reply(
                email, decision.reasoning,
                category=decision.category,
                style_profile=style_profile,
                kb_context=kb_context,
            )
            draft_data = {
                "to": draft.to,
                "cc": draft.cc,
                "subject": draft.subject,
                "body": draft.body,
                "thread_id": draft.thread_id,
            }

        if req.apply_labels:
            apply_label(email.id, decision.category.value)

        if req.mark_as_read:
            try:
                from .gmail_client import _get_service
                svc = _get_service()
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

        results.append({
            "email_id":  email.id,
            "from_addr": email.from_addr,
            "subject":   email.subject,
            "date":      email.date,
            "snippet":   email.snippet,
            "category":  decision.category.value,
            "priority":  decision.priority,
            "reasoning": decision.reasoning,
            "suggested_action": decision.suggested_action,
            "excluded":  skip_draft,
            "draft":     draft_data,
        })

    return {"count": len(results), "emails": results}


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
            # Compose flow — no prior log entry; create one now
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
    return {
        "count": len(emails),
        "emails": [
            {
                "email_id": e.id,
                "to": e.to,
                "subject": e.subject,
                "date": e.date,
                "snippet": e.snippet,
                "thread_id": e.thread_id,
            }
            for e in emails
        ],
    }


class FollowupDraftRequest(BaseModel):
    email_id: str
    to: list[str]
    subject: str
    snippet: str
    thread_id: str | None = None
    days: int = 3


@app.post("/followups/draft")
def api_followup_draft(req: FollowupDraftRequest) -> dict:
    from .schemas import Email as EmailSchema
    stub = EmailSchema(
        id=req.email_id,
        thread_id=req.thread_id or req.email_id,
        from_addr="me",
        to=req.to,
        subject=req.subject,
        snippet=req.snippet,
        body=req.snippet,
    )
    draft = generate_followup(stub, days=req.days)
    return {"to": draft.to, "subject": draft.subject, "body": draft.body,
            "thread_id": draft.thread_id}


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
    profile = get_style_profile()
    return {"profile": profile}


@app.post("/style/learn")
def api_learn_style() -> dict:
    try:
        emails = fetch_sent_sample(max_results=25)
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

class KbRequest(BaseModel):
    title: str
    content: str


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
