"""Gmail API client: OAuth, fetch unread, save draft."""
from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import settings
from .schemas import DraftReply, Email, ThreadMessage

logger = logging.getLogger(__name__)

# Read + compose + modify. No send — drafts only (safer default).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _get_service():
    """Authorize and return a Gmail API service object."""
    creds: Credentials | None = None

    if settings.gmail_token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(settings.gmail_token_path), SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.debug("Refreshing expired Gmail token")
            creds.refresh(Request())
        else:
            if not settings.gmail_credentials_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {settings.gmail_credentials_path}. "
                    "Download OAuth client JSON from Google Cloud Console."
                )
            logger.info("Opening browser for Gmail OAuth consent")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.gmail_credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        settings.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
        settings.gmail_token_path.write_text(creds.to_json())
        logger.debug("Gmail token saved to %s", settings.gmail_token_path)

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _extract_body(payload: dict[str, Any]) -> str:
    """Walk the MIME tree and pull out text/plain (or fall back to text/html)."""
    if not payload:
        return ""

    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if mime_type.startswith("text/") and body_data:
        try:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
        except Exception:
            return ""

    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []) or []:
        body = _extract_body(part)
        if body:
            return body

    return ""


def _parse_addrs(value: str) -> list[str]:
    if not value:
        return []
    return [a.strip() for a in value.split(",") if a.strip()]


def _headers_to_dict(headers: list[dict[str, str]]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers}


def _fetch_thread_context(
    service, thread_id: str, current_msg_id: str, max_messages: int = 3
) -> list[ThreadMessage]:
    """Return the last `max_messages` prior messages in the thread (chronological order)."""
    try:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
    except Exception as e:
        logger.warning("Could not fetch thread %s: %s", thread_id, e)
        return []

    context: list[ThreadMessage] = []
    for msg in thread.get("messages", []):
        if msg["id"] == current_msg_id:
            continue
        payload = msg.get("payload", {})
        headers = _headers_to_dict(payload.get("headers", []))
        body = _extract_body(payload)
        if body:
            context.append(
                ThreadMessage(
                    from_addr=headers.get("from", ""),
                    date=headers.get("date", ""),
                    body=body[:2000],
                )
            )

    # Keep the last N in chronological order (messages arrive in order from the API).
    return context[-max_messages:]


def fetch_emails(query: str | None = None, max_results: int | None = None) -> list[Email]:
    """Fetch emails matching the query."""
    service = _get_service()
    q = query or settings.inbox_query
    n = max_results or settings.max_emails_per_run

    logger.debug("Gmail list query=%r max=%d", q, n)
    result = service.users().messages().list(userId="me", q=q, maxResults=n).execute()
    message_ids = [m["id"] for m in result.get("messages", [])]
    logger.info("Gmail returned %d message(s)", len(message_ids))

    emails: list[Email] = []
    for mid in message_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=mid, format="full")
            .execute()
        )
        payload = msg.get("payload", {})
        headers = _headers_to_dict(payload.get("headers", []))
        thread_ctx = _fetch_thread_context(service, msg["threadId"], msg["id"])

        emails.append(
            Email(
                id=msg["id"],
                thread_id=msg["threadId"],
                from_addr=headers.get("from", ""),
                to=_parse_addrs(headers.get("to", "")),
                cc=_parse_addrs(headers.get("cc", "")),
                subject=headers.get("subject", ""),
                snippet=msg.get("snippet", ""),
                body=_extract_body(payload),
                date=headers.get("date", ""),
                labels=msg.get("labelIds", []),
                thread_messages=thread_ctx,
            )
        )
        logger.debug("Fetched email %s — %r", mid, headers.get("subject", ""))

    return emails


def save_draft(draft: DraftReply) -> str:
    """Save a draft to Gmail. Returns the draft ID."""
    service = _get_service()

    msg = EmailMessage()
    msg["To"] = ", ".join(draft.to)
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    msg["Subject"] = draft.subject
    msg.set_content(draft.body)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict[str, Any] = {"message": {"raw": raw}}
    if draft.thread_id:
        body["message"]["threadId"] = draft.thread_id

    created = service.users().drafts().create(userId="me", body=body).execute()
    draft_id = created["id"]
    logger.info("Saved Gmail draft %s — %r", draft_id, draft.subject)
    return draft_id
