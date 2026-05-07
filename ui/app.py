"""Streamlit UI for the email agent."""
from __future__ import annotations

import html
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from email_agent.config import settings                            # noqa: E402
from email_agent.gmail_client import fetch_emails, save_draft      # noqa: E402
from email_agent.llm import draft_reply, triage_email              # noqa: E402
from email_agent.schemas import (                                  # noqa: E402
    DraftReply,
    ProcessedEmail,
    TriageCategory,
)

st.set_page_config(
    page_title="Email Agent",
    page_icon="✉️",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS_PATH = Path(__file__).parent / "styles.css"
if CSS_PATH.exists():
    st.markdown(f"<style>{CSS_PATH.read_text()}</style>", unsafe_allow_html=True)

DRAFT_CATEGORIES = {TriageCategory.REPLY_NEEDED, TriageCategory.MEETING, TriageCategory.ACTION_REQUIRED}


# =========================================================================
# Session state
# =========================================================================
def _init_state() -> None:
    defaults: dict = {
        "processed": [],
        "saved_ids": [],
        "saved_email_ids": set(),
        "log_lines": [],
        "running": False,
        "last_run_at": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

_init_state()


# =========================================================================
# Pipeline
# =========================================================================
def _log(msg: str, tag: str = "") -> None:
    ts = time.strftime("%H:%M:%S")
    cls = f"ea-log-{tag}" if tag else ""
    st.session_state.log_lines.append(
        f'<p class="ea-log-line {cls}">[{ts}] {html.escape(msg)}</p>'
    )

def _render_log(placeholder) -> None:
    if not st.session_state.log_lines:
        return
    joined = "".join(st.session_state.log_lines[-60:])
    placeholder.markdown(f'<div class="ea-log">{joined}</div>', unsafe_allow_html=True)


def run_pipeline(query: str, max_emails: int) -> None:
    st.session_state.processed = []
    st.session_state.saved_ids = []
    st.session_state.saved_email_ids = set()
    st.session_state.log_lines = []
    st.session_state.running = True

    log_placeholder = st.empty()

    try:
        _log(f"Fetching emails — query={query!r}, max={max_emails}", "fetch")
        _render_log(log_placeholder)
        emails = fetch_emails(query=query, max_results=max_emails)
        _log(f"Found {len(emails)} email(s)", "fetch")
        _render_log(log_placeholder)

        if not emails:
            _log("No emails matched the query.", "fetch")
            _render_log(log_placeholder)
            return

        processed: list[ProcessedEmail] = []
        for i, email in enumerate(emails, 1):
            subject_preview = email.subject[:55] or "(no subject)"
            _log(f"[{i}/{len(emails)}] Triaging — {subject_preview}", "triage")
            _render_log(log_placeholder)

            try:
                decision = triage_email(email)
            except Exception as e:  # noqa: BLE001
                _log(f"Triage failed: {e}", "error")
                _render_log(log_placeholder)
                continue

            _log(f"  → {decision.category.value} ({decision.priority}) — {decision.reasoning}", "triage")
            _render_log(log_placeholder)

            pe = ProcessedEmail(email=email, triage=decision)

            if decision.category in DRAFT_CATEGORIES:
                _log("  Drafting reply…", "draft")
                _render_log(log_placeholder)
                try:
                    draft = draft_reply(email, decision.reasoning, category=decision.category)
                    pe = pe.model_copy(update={"draft": draft})
                    _log(f"  Draft ready ({len(draft.body)} chars)", "draft")
                except Exception as e:  # noqa: BLE001
                    _log(f"  Draft failed: {e}", "error")
                    pe = pe.model_copy(update={"error": str(e)})
                _render_log(log_placeholder)

            processed.append(pe)

        st.session_state.processed = processed
        st.session_state.last_run_at = time.strftime("%H:%M:%S")
        _log(f"Done — {len(processed)} email(s) processed.", "fetch")
        _render_log(log_placeholder)

    finally:
        st.session_state.running = False


# =========================================================================
# Save helpers
# =========================================================================
def save_single_draft(pe: ProcessedEmail, edited_body: str, edited_subject: str) -> None:
    if not pe.draft:
        return
    draft_to_save = DraftReply(
        to=pe.draft.to, cc=pe.draft.cc,
        subject=edited_subject, body=edited_body,
        in_reply_to_id=pe.draft.in_reply_to_id,
        thread_id=pe.draft.thread_id,
    )
    try:
        draft_id = save_draft(draft_to_save)
        st.session_state.saved_ids.append(draft_id)
        st.session_state.saved_email_ids.add(pe.email.id)
        st.toast(f"Draft saved ({draft_id[:8]}…)", icon="✅")
    except Exception as e:  # noqa: BLE001
        st.toast(f"Save failed: {e}", icon="❌")


def save_all_drafts() -> None:
    count = 0
    for i, pe in enumerate(st.session_state.processed):
        if pe.draft is None or pe.email.id in st.session_state.saved_email_ids:
            continue
        try:
            draft_id = save_draft(pe.draft)
            st.session_state.saved_ids.append(draft_id)
            st.session_state.saved_email_ids.add(pe.email.id)
            count += 1
        except Exception as e:  # noqa: BLE001
            st.toast(f"Failed to save #{i}: {e}", icon="⚠️")
    st.toast(f"Saved {count} draft(s) to Gmail", icon="✅")


# =========================================================================
# HTML helpers
# =========================================================================
def _badge(text: str, kind: str) -> str:
    return f'<span class="ea-badge ea-badge-{kind}">{html.escape(text)}</span>'

def _stats_html(processed: list[ProcessedEmail], saved_count: int) -> str:
    total    = len(processed)
    drafted  = sum(1 for p in processed if p.draft is not None)
    high     = sum(1 for p in processed if p.triage.priority == "high")
    return f"""
    <div class="ea-stats">
        <div class="ea-stat ea-stat-processed">
            <div class="ea-stat-value">{total}</div>
            <div class="ea-stat-label">Processed</div>
        </div>
        <div class="ea-stat ea-stat-drafted">
            <div class="ea-stat-value">{drafted}</div>
            <div class="ea-stat-label">Drafts ready</div>
        </div>
        <div class="ea-stat ea-stat-high">
            <div class="ea-stat-value">{high}</div>
            <div class="ea-stat-label">High priority</div>
        </div>
        <div class="ea-stat ea-stat-saved">
            <div class="ea-stat-value">{saved_count}</div>
            <div class="ea-stat-label">Saved to Gmail</div>
        </div>
    </div>
    """

def _card_header_html(pe: ProcessedEmail) -> str:
    e, t = pe.email, pe.triage
    prio_class = f"ea-card-{t.priority}"
    return f"""
    <div class="ea-card {prio_class}">
    <div class="ea-card-inner">
        <div class="ea-card-header">
            <div class="ea-card-from">{html.escape(e.from_addr)}</div>
            <div class="ea-card-date">{html.escape(e.date[:24])}</div>
        </div>
        <div class="ea-card-subject">{html.escape(e.subject or "(no subject)")}</div>
        <div class="ea-card-snippet">{html.escape(e.snippet)}</div>
        <div class="ea-card-footer">
            {_badge(t.category.value.replace("_", " "), t.category.value)}
            {_badge(t.priority + " priority", f"prio-{t.priority}")}
        </div>
        <div class="ea-reasoning">
            <span class="ea-reasoning-label">Why</span>{html.escape(t.reasoning)}
        </div>
    </div>
    """


# =========================================================================
# Sidebar
# =========================================================================
with st.sidebar:
    # Brand strip
    st.markdown(
        f"""
        <div class="ea-brand">
            <div class="ea-brand-icon">✉</div>
            <div>
                <div class="ea-brand-name">Email Agent</div>
                <div class="ea-brand-sub">{settings.openai_model} · OpenAI</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ea-sidebar-section">Search</div>', unsafe_allow_html=True)

    PRESETS: dict[str, str] = {
        "Unread (last 3 days)":      "is:unread newer_than:3d",
        "Unread inbox only":         "is:unread -category:promotions -category:social",
        "All unread":                "is:unread",
        "Important & unread":        "is:unread label:important",
        "Unread with attachments":   "is:unread has:attachment newer_than:7d",
        "From a specific person":    "is:unread from:",
        "Custom query":              "__custom__",
    }

    selected_preset = st.selectbox(
        "Query preset",
        options=list(PRESETS.keys()),
        label_visibility="collapsed",
    )
    preset_val = PRESETS[selected_preset]

    if preset_val == "__custom__":
        query = st.text_input(
            "Custom query",
            value=settings.inbox_query,
            label_visibility="collapsed",
            placeholder="Gmail search query…",
        )
    else:
        query = preset_val
        st.markdown(f'<div class="ea-query-preview">{query}</div>', unsafe_allow_html=True)

    max_emails = st.slider("Max emails", min_value=1, max_value=50, value=settings.max_emails_per_run)

    st.markdown('<div class="ea-sidebar-section">Actions</div>', unsafe_allow_html=True)

    run_disabled = st.session_state.running
    if st.button("Run agent", type="primary", use_container_width=True, disabled=run_disabled):
        run_pipeline(query, max_emails)
        st.rerun()

    has_unsaved = st.session_state.processed and any(
        p.draft and p.email.id not in st.session_state.saved_email_ids
        for p in st.session_state.processed
    )
    if has_unsaved:
        if st.button("Save all drafts", use_container_width=True, disabled=run_disabled):
            save_all_drafts()
            st.rerun()

    if st.session_state.processed:
        if st.button("Clear results", use_container_width=True):
            st.session_state.processed = []
            st.session_state.saved_ids = []
            st.session_state.saved_email_ids = set()
            st.session_state.log_lines = []
            st.rerun()

    if st.session_state.last_run_at:
        st.markdown(
            f'<div style="font-size:0.72rem;color:#4a5070;padding:12px 0 0 2px">Last run {st.session_state.last_run_at}</div>',
            unsafe_allow_html=True,
        )


# =========================================================================
# Main area
# =========================================================================
has_results = bool(st.session_state.processed)
dot_class = "ea-header-dot" if has_results else "ea-header-dot idle"

st.markdown(
    f"""
    <div class="ea-header">
        <div class="ea-header-left">
            <div class="{dot_class}"></div>
            <h1 class="ea-header-title">Inbox</h1>
        </div>
        <div class="ea-header-meta">
            <span class="ea-pill">LangGraph</span>
            <span class="ea-pill">OpenAI</span>
            <span class="ea-pill">{settings.openai_model}</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Live log
if st.session_state.log_lines:
    joined = "".join(st.session_state.log_lines[-60:])
    st.markdown(f'<div class="ea-log">{joined}</div>', unsafe_allow_html=True)

# Stats row
if has_results:
    st.markdown(
        _stats_html(st.session_state.processed, len(st.session_state.saved_ids)),
        unsafe_allow_html=True,
    )

# Empty state
if not has_results and not st.session_state.running:
    st.markdown(
        """
        <div class="ea-empty">
            <span class="ea-empty-icon">📬</span>
            <div class="ea-empty-title">No results yet</div>
            <div class="ea-empty-sub">
                Enter a Gmail search query in the sidebar and press
                <strong>Run agent</strong> to triage your inbox.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Email cards
if has_results:
    # Filter bar
    filter_cols = st.columns([2, 3, 5])
    with filter_cols[0]:
        show_drafted_only = st.checkbox("Drafted only", value=False)
    with filter_cols[1]:
        all_cats = sorted({p.triage.category.value for p in st.session_state.processed})
        selected_cats = st.multiselect(
            "Categories",
            options=all_cats,
            default=all_cats,
            label_visibility="collapsed",
            placeholder="Filter by category…",
        )

    visible = [
        p for p in st.session_state.processed
        if (not show_drafted_only or p.draft is not None)
        and p.triage.category.value in selected_cats
    ]

    if not visible:
        st.markdown(
            '<div style="text-align:center;color:#4a5070;padding:32px 0;font-size:0.875rem">No emails match the current filter.</div>',
            unsafe_allow_html=True,
        )

    for idx, pe in enumerate(visible):
        # Card open + header
        st.markdown(_card_header_html(pe), unsafe_allow_html=True)

        # Full body expander (inside the card visually via CSS)
        with st.expander("Show full email body"):
            st.text(pe.email.body[:4000] or "(empty body)")

        # Draft editor
        if pe.draft:
            st.markdown(
                '<div class="ea-draft-block"><div class="ea-draft-label">✦ Generated draft</div>',
                unsafe_allow_html=True,
            )
            key_prefix = f"draft_{idx}_{pe.email.id}"
            subj = st.text_input("Subject", value=pe.draft.subject, key=f"{key_prefix}_subj", label_visibility="collapsed")
            body = st.text_area("Body", value=pe.draft.body, height=180, key=f"{key_prefix}_body", label_visibility="collapsed")

            c1, c2, _ = st.columns([1.4, 1.4, 5])
            with c1:
                saved_already = pe.email.id in st.session_state.saved_email_ids
                label = "Saved ✓" if saved_already else "Save to Gmail"
                if st.button(label, key=f"{key_prefix}_save", type="primary", disabled=saved_already):
                    save_single_draft(pe, body, subj)
                    st.rerun()
            with c2:
                if st.button("Regenerate", key=f"{key_prefix}_regen"):
                    try:
                        new_draft = draft_reply(pe.email, pe.triage.reasoning, category=pe.triage.category)
                        st.session_state.processed[st.session_state.processed.index(pe)] = (
                            pe.model_copy(update={"draft": new_draft})
                        )
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.toast(f"Regenerate failed: {e}", icon="❌")

            st.markdown("</div>", unsafe_allow_html=True)

        # Card close
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
