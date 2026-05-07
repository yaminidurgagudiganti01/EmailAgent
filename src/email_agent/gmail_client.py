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
from googleapiclient.errors import HttpError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .config import settings
from .schemas import DraftReply, Email, ThreadMessage

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

# EmailAgent label namespace → Gmail label name
CATEGORY_LABELS: dict[str, str] = {
    "action_required": "EmailAgent/Urgent",
    "reply_needed":    "EmailAgent/Work",
    "meeting":         "EmailAgent/Meeting",
    "fyi":             "EmailAgent/FYI",
    "newsletter":      "EmailAgent/Newsletter",
    "spam":            "EmailAgent/Spam",
}

_label_id_cache: dict[str, str] = {}  # name → Gmail label id


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        return exc.resp.status in (429, 500, 502, 503)
    return False


_gmail_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)


def _ensure_label(service, name: str) -> str:
    """Return the Gmail label ID for `name`, creating it if it doesn't exist."""
    if name in _label_id_cache:
        return _label_id_cache[name]

    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for lbl in labels:
        if lbl["name"] == name:
            _label_id_cache[name] = lbl["id"]
            return lbl["id"]

    created = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow",
              "messageListVisibility": "show"},
    ).execute()
    _label_id_cache[name] = created["id"]
    logger.debug("Created Gmail label %r (%s)", name, created["id"])
    return created["id"]


def apply_label(email_id: str, category: str) -> None:
    """Apply the EmailAgent Gmail label matching `category` to an email."""
    label_name = CATEGORY_LABELS.get(category)
    if not label_name:
        return
    try:
        service = _get_service()
        label_id = _ensure_label(service, label_name)
        service.users().messages().modify(
            userId="me", id=email_id, body={"addLabelIds": [label_id]}
        ).execute()
        logger.debug("Applied label %r to email %s", label_name, email_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Label apply failed for %s: %s", email_id, e)


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


@_gmail_retry
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


@_gmail_retry
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


@_gmail_retry
def send_email(draft: DraftReply) -> str:
    """Send an email immediately via Gmail. Returns the sent message ID."""
    service = _get_service()

    msg = EmailMessage()
    msg["To"] = ", ".join(draft.to)
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    msg["Subject"] = draft.subject
    msg.set_content(draft.body)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    body: dict[str, Any] = {"raw": raw}
    if draft.thread_id:
        body["threadId"] = draft.thread_id

    sent = service.users().messages().send(userId="me", body=body).execute()
    message_id = sent["id"]
    logger.info("Sent email %s — %r", message_id, draft.subject)
    return message_id


@_gmail_retry
def fetch_sent_no_reply(days: int = 3, max_results: int = 10) -> list[Email]:
    """Return sent emails older than `days` days that received no reply."""
    service = _get_service()

    result = (
        service.users()
        .messages()
        .list(userId="me", q=f"in:sent older_than:{days}d", maxResults=max_results * 4)
        .execute()
    )
    message_ids = [m["id"] for m in result.get("messages", [])]

    candidates: list[Email] = []
    for mid in message_ids:
        if len(candidates) >= max_results:
            break
        msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=msg["threadId"], format="minimal")
            .execute()
        )
        if len(thread.get("messages", [])) > 1:
            continue  # already has a reply

        payload = msg.get("payload", {})
        headers = _headers_to_dict(payload.get("headers", []))
        candidates.append(
            Email(
                id=msg["id"],
                thread_id=msg["threadId"],
                from_addr=headers.get("from", ""),
                to=_parse_addrs(headers.get("to", "")),
                subject=headers.get("subject", ""),
                snippet=msg.get("snippet", ""),
                body=_extract_body(payload),
                date=headers.get("date", ""),
                labels=msg.get("labelIds", []),
            )
        )
        logger.debug("Follow-up candidate: %s — %r", mid, headers.get("subject", ""))

    logger.info("Found %d sent email(s) with no reply (>%d days)", len(candidates), days)
    return candidates


@_gmail_retry
def fetch_sent_sample(max_results: int = 25) -> list[Email]:
    """Fetch recent sent emails for writing-style analysis."""
    service = _get_service()
    result = (
        service.users()
        .messages()
        .list(userId="me", q="in:sent", maxResults=max_results)
        .execute()
    )
    message_ids = [m["id"] for m in result.get("messages", [])]

    emails: list[Email] = []
    for mid in message_ids:
        msg = service.users().messages().get(userId="me", id=mid, format="full").execute()
        payload = msg.get("payload", {})
        headers = _headers_to_dict(payload.get("headers", []))
        body = _extract_body(payload)
        if not body.strip():
            continue
        emails.append(
            Email(
                id=msg["id"],
                thread_id=msg["threadId"],
                from_addr=headers.get("from", ""),
                to=_parse_addrs(headers.get("to", "")),
                subject=headers.get("subject", ""),
                snippet=msg.get("snippet", ""),
                body=body,
                date=headers.get("date", ""),
                labels=msg.get("labelIds", []),
            )
        )
        logger.debug("Style sample: %s — %r", mid, headers.get("subject", ""))

    logger.info("Fetched %d sent email(s) for style analysis", len(emails))
    return emails
