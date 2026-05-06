# Email Drafting Agent

Local-LLM email triage and drafting agent. Reads your Gmail inbox, classifies
each message, and saves polite reply drafts for the ones that need one.
Nothing is ever sent automatically — everything lands in **Gmail → Drafts**
for you to review.

**Stack**

- [LangGraph 1.1](https://langchain-ai.github.io/langgraph/) — state machine
- [langchain-ollama](https://pypi.org/project/langchain-ollama/) — local LLM via [Ollama](https://ollama.com)
- [Gmail API](https://developers.google.com/gmail/api) via OAuth
- Pydantic v2, `uv` for package management

---

## 1. Install Ollama + pull a tool-calling model

Qwen3 and Llama 3.1+ have solid tool-calling / structured-output support.

```bash
# Install Ollama from https://ollama.com
ollama pull qwen3:8b        # recommended default
# or:  ollama pull llama3.1:8b
ollama serve                # usually runs automatically
```

## 2. Set up Gmail OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable the **Gmail API**
3. Configure an OAuth consent screen (External, add yourself as a test user)
4. Create OAuth client ID → **Desktop app** → download the JSON
5. Save it as `config/credentials.json`

The first run will open a browser for consent and cache a token in `config/token.json`.

## 3. Install the project

```bash
# Install uv: https://docs.astral.sh/uv/
cd email-agent
uv venv
uv pip install -e ".[dev]"

cp .env.example .env   # edit USER_NAME, OLLAMA_MODEL, etc.
```

## 4. Run

### Option A — CLI

```bash
# Triage unread mail and save reply drafts to Gmail Drafts
python -m email_agent

# Custom query, more emails
python -m email_agent --query "is:unread newer_than:1d" --max 25

# Dry run — triage and draft, but don't hit Gmail Drafts API
python -m email_agent --dry-run
```

### Option B — Streamlit UI

```bash
streamlit run ui/app.py
```

Opens at `http://localhost:8501`. Configure query and model from the sidebar,
watch live progress, edit each draft inline, and save per-email or all at once.

![UI layout: sidebar config + stats row + per-email cards with editable draft](./docs/ui-preview.png)

You'll see a table of triaged emails and a count of drafts saved. Open Gmail
and review the drafts before sending.

---

## How it works

```
        ┌───────┐
  START →│ fetch │──▶ pulls N emails matching the query
        └───┬───┘
            ▼
        ┌───────┐
        │triage │──▶ LLM classifies each email into one of 6 categories
        └───┬───┘     (structured output via Pydantic)
            ▼
        ┌───────┐
        │ draft │──▶ For reply_needed / meeting: LLM writes a draft body
        └───┬───┘
            ▼
        ┌───────┐
        │ save  │──▶ POST to Gmail Drafts API (threaded correctly)
        └───┬───┘
            ▼
           END
```

### Triage categories

| Category | Draft created? |
|---|---|
| `reply_needed` | ✓ |
| `meeting` | ✓ |
| `action_required` | ✗ (flagged in summary) |
| `fyi` | ✗ |
| `newsletter` | ✗ |
| `spam` | ✗ |

### Where to customise

- **Prompts**: `src/email_agent/llm.py` — `TRIAGE_SYSTEM` and `DRAFT_SYSTEM`
- **Triage schema**: `src/email_agent/schemas.py` — add categories or fields
- **Which categories get drafted**: `src/email_agent/agent.py` → `DRAFT_CATEGORIES`
- **Add nodes** (e.g. calendar lookup, thread history fetch): edit `agent.py`

### Suggested next steps

1. **Thread context** — extend `gmail_client.fetch_emails` to also pull the
   last few messages in the thread and pass them to `draft_reply`.
2. **Human-in-the-loop** — LangGraph 1.0+ has first-class interrupts. Add an
   `interrupt()` call between `draft` and `save` so you can approve/edit each
   draft in a CLI or web UI.
3. **Persistence** — add a LangGraph checkpointer (SQLite) so re-runs can
   resume and you can replay failed triages.
4. **Calendar tool** — give the drafting LLM a `check_calendar` tool so it can
   propose actual free times for meeting replies.

### Security notes

- OAuth scopes used: `gmail.readonly`, `gmail.compose`, `gmail.modify`
  (no `gmail.send` — the agent physically cannot send mail)
- All LLM inference is local via Ollama. No email content leaves your machine.
- `config/token.json` contains refresh tokens — keep it out of git (it's in
  `.gitignore`).
