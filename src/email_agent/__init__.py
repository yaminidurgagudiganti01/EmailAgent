"""Email drafting agent — LangGraph + OpenAI."""
from .agent import build_graph, graph
from .config import settings
from .schemas import DraftReply, Email, ProcessedEmail, ThreadMessage, TriageCategory, TriageDecision
from .store import is_processed, mark_processed, processed_count

__all__ = [
    "DraftReply",
    "Email",
    "ProcessedEmail",
    "ThreadMessage",
    "TriageCategory",
    "TriageDecision",
    "build_graph",
    "graph",
    "is_processed",
    "mark_processed",
    "processed_count",
    "settings",
]
