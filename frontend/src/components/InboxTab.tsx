"use client";
import { useState } from "react";
import { api, type EmailResult, type RunRequest } from "@/lib/api";
import clsx from "clsx";

const PRIORITY_ICON: Record<string, string> = { high: "🔴", medium: "🟡", low: "🟢" };
const PRESETS: Record<string, string> = {
  "Unread (last 3 days)":    "is:unread newer_than:3d",
  "Unread inbox only":       "is:unread -category:promotions -category:social",
  "All unread":              "is:unread",
  "Important & unread":      "is:unread label:important",
  "Unread with attachments": "is:unread has:attachment newer_than:7d",
};

export default function InboxTab() {
  const [preset, setPreset]         = useState(Object.keys(PRESETS)[0]);
  const [maxEmails, setMaxEmails]   = useState(10);
  const [applyLabels, setApply]     = useState(true);
  const [markRead, setMarkRead]     = useState(false);
  const [loading, setLoading]       = useState(false);
  const [emails, setEmails]         = useState<EmailResult[]>([]);
  const [error, setError]           = useState("");
  const [savedIds, setSavedIds]     = useState<Set<string>>(new Set());
  const [sentIds, setSentIds]       = useState<Set<string>>(new Set());
  const [confirmSend, setConfirm]   = useState<string | null>(null);
  const [editedDrafts, setEdited]   = useState<Record<string, { subject: string; body: string }>>({});

  async function runAgent() {
    setLoading(true); setError(""); setEmails([]);
    setSavedIds(new Set()); setSentIds(new Set());
    try {
      const res = await api.run({
        query: PRESETS[preset],
        max_emails: maxEmails,
        apply_labels: applyLabels,
        mark_as_read: markRead,
      } as RunRequest);
      setEmails(res.emails);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  function getDraft(e: EmailResult) {
    return editedDrafts[e.email_id] ?? { subject: e.draft?.subject ?? "", body: e.draft?.body ?? "" };
  }

  async function saveDraft(e: EmailResult) {
    const d = getDraft(e);
    try {
      await api.saveDraft({ to: e.draft!.to, subject: d.subject, body: d.body,
                            thread_id: e.draft!.thread_id, email_id: e.email_id });
      setSavedIds(s => new Set([...s, e.email_id]));
    } catch (err: unknown) {
      alert("Save failed: " + (err instanceof Error ? err.message : err));
    }
  }

  async function sendNow(e: EmailResult) {
    const d = getDraft(e);
    try {
      await api.sendEmail({ to: e.draft!.to, subject: d.subject, body: d.body,
                            thread_id: e.draft!.thread_id, email_id: e.email_id });
      setSentIds(s => new Set([...s, e.email_id]));
      setConfirm(null);
    } catch (err: unknown) {
      alert("Send failed: " + (err instanceof Error ? err.message : err));
    }
  }

  const drafted = emails.filter(e => e.draft).length;
  const high    = emails.filter(e => e.priority === "high").length;

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-slate-900">📬 Inbox</h1>
        {emails.length > 0 && (
          <div className="flex gap-3 text-sm text-slate-500">
            <span>{emails.length} processed</span>
            <span>{drafted} drafts</span>
            <span>{high} high priority</span>
            <span>{sentIds.size} sent</span>
          </div>
        )}
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Query</label>
            <select
              value={preset}
              onChange={e => setPreset(e.target.value)}
              className="mt-1 w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              {Object.keys(PRESETS).map(p => <option key={p}>{p}</option>)}
            </select>
            <p className="mt-1 text-xs text-indigo-500 font-mono">{PRESETS[preset]}</p>
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Max emails: {maxEmails}
            </label>
            <input type="range" min={1} max={50} value={maxEmails}
              onChange={e => setMaxEmails(+e.target.value)}
              className="mt-2 w-full accent-indigo-500"
            />
          </div>
        </div>
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={applyLabels} onChange={e => setApply(e.target.checked)}
              className="accent-indigo-500" />
            Apply Gmail labels
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={markRead} onChange={e => setMarkRead(e.target.checked)}
              className="accent-indigo-500" />
            Mark as read
          </label>
        </div>
        <button
          onClick={runAgent}
          disabled={loading}
          className="w-full bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60 text-white font-semibold py-2 rounded-lg transition-colors"
        >
          {loading ? "Running…" : "Run Agent"}
        </button>
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </div>

      {/* Email cards */}
      {emails.map(e => (
        <div
          key={e.email_id}
          className={clsx(
            "bg-white rounded-xl border border-slate-200 overflow-hidden",
            e.priority === "high"   && "border-l-4 border-l-red-400",
            e.priority === "medium" && "border-l-4 border-l-amber-400",
          )}
        >
          <div className="p-4">
            <div className="flex justify-between items-start mb-1">
              <span className="font-semibold text-sm text-slate-800 truncate">{e.from_addr}</span>
              <span className="text-xs text-slate-400 shrink-0">{e.date.slice(0, 16)}</span>
            </div>
            <p className="font-semibold text-slate-900 mb-1">{e.subject || "(no subject)"}</p>
            <p className="text-sm text-slate-500 line-clamp-2 mb-3">{e.snippet}</p>
            <div className="flex gap-2">
              <CategoryBadge cat={e.category} />
              <span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-600">
                {PRIORITY_ICON[e.priority]} {e.priority}
              </span>
              {e.excluded && <span className="text-xs px-2 py-0.5 rounded-full bg-orange-100 text-orange-700">excluded</span>}
            </div>
            <p className="mt-2 text-xs text-indigo-600 bg-indigo-50 rounded px-2 py-1">
              <span className="font-bold">WHY </span>{e.reasoning}
            </p>
          </div>

          {e.draft && !e.excluded && (
            <div className="border-t border-slate-100 bg-green-50 p-4 space-y-2">
              <p className="text-xs font-bold text-green-700 uppercase tracking-wide">🤖 AI Draft</p>
              <input
                className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white"
                value={getDraft(e).subject}
                onChange={ev => setEdited(d => ({ ...d, [e.email_id]: { ...getDraft(e), subject: ev.target.value } }))}
              />
              <textarea
                rows={4}
                className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white resize-none"
                value={getDraft(e).body}
                onChange={ev => setEdited(d => ({ ...d, [e.email_id]: { ...getDraft(e), body: ev.target.value } }))}
              />
              <div className="flex gap-2">
                {sentIds.has(e.email_id) ? (
                  <span className="text-green-600 text-sm font-semibold">📤 Sent</span>
                ) : savedIds.has(e.email_id) ? (
                  <span className="text-indigo-600 text-sm font-semibold">📁 Saved</span>
                ) : (
                  <>
                    <button onClick={() => saveDraft(e)}
                      className="px-3 py-1.5 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold">
                      Save Draft
                    </button>
                    <button onClick={() => setConfirm(e.email_id)}
                      className="px-3 py-1.5 bg-green-500 text-white text-sm rounded-lg hover:bg-green-600 font-semibold">
                      📤 Send Now
                    </button>
                  </>
                )}
              </div>
              {confirmSend === e.email_id && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
                  <p className="text-sm text-amber-800 font-medium">
                    ⚠️ Send to <strong>{e.draft.to.join(", ")}</strong>? This cannot be undone.
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => sendNow(e)}
                      className="px-3 py-1 bg-green-500 text-white text-sm rounded-lg font-semibold">
                      ✅ Confirm Send
                    </button>
                    <button onClick={() => setConfirm(null)}
                      className="px-3 py-1 bg-slate-200 text-slate-700 text-sm rounded-lg">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function CategoryBadge({ cat }: { cat: string }) {
  const styles: Record<string, string> = {
    reply_needed:    "bg-green-100 text-green-700",
    meeting:         "bg-blue-100 text-blue-700",
    action_required: "bg-amber-100 text-amber-700",
    fyi:             "bg-slate-100 text-slate-600",
    newsletter:      "bg-purple-100 text-purple-700",
    spam:            "bg-red-100 text-red-700",
  };
  return (
    <span className={clsx("text-xs px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide", styles[cat] ?? "bg-slate-100 text-slate-600")}>
      {cat.replace("_", " ")}
    </span>
  );
}
