"use client";
import { useState } from "react";
import { api, type FollowupEmail, type DraftData } from "@/lib/api";

export default function FollowupsTab() {
  const [days, setDays]       = useState(3);
  const [max, setMax]         = useState(20);
  const [loading, setLoading] = useState(false);
  const [emails, setEmails]   = useState<FollowupEmail[]>([]);
  const [error, setError]     = useState("");

  const [draftLoading, setDL] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts]   = useState<Record<string, DraftData & { subject: string; body: string }>>({});
  const [sentIds, setSent]    = useState<Set<string>>(new Set());
  const [savedIds, setSaved]  = useState<Set<string>>(new Set());
  const [confirm, setConfirm] = useState<string | null>(null);

  async function scan() {
    setLoading(true); setError(""); setEmails([]);
    setDrafts({}); setSent(new Set()); setSaved(new Set());
    try {
      const res = await api.scanFollowups({ days, max_emails: max });
      setEmails(res.emails);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function generateDraft(e: FollowupEmail) {
    setDL(d => ({ ...d, [e.email_id]: true }));
    try {
      const res = await fetch("/api/followups/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email_id: e.email_id, to: e.to, subject: e.subject,
                               snippet: e.snippet, thread_id: e.thread_id, days }),
      });
      if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
      const d: DraftData = await res.json();
      setDrafts(prev => ({ ...prev, [e.email_id]: { ...d, subject: d.subject, body: d.body } }));
    } catch (err: unknown) {
      alert("Draft failed: " + (err instanceof Error ? err.message : err));
    } finally {
      setDL(d => ({ ...d, [e.email_id]: false }));
    }
  }

  async function save(e: FollowupEmail) {
    const d = drafts[e.email_id];
    if (!d) return;
    try {
      await api.saveDraft({ to: d.to, subject: d.subject, body: d.body,
                            thread_id: d.thread_id ?? undefined, email_id: e.email_id });
      setSaved(s => new Set([...s, e.email_id]));
    } catch (err: unknown) {
      alert("Save failed: " + (err instanceof Error ? err.message : err));
    }
  }

  async function send(e: FollowupEmail) {
    const d = drafts[e.email_id];
    if (!d) return;
    try {
      await api.sendEmail({ to: d.to, subject: d.subject, body: d.body,
                            thread_id: d.thread_id ?? undefined, email_id: e.email_id });
      setSent(s => new Set([...s, e.email_id]));
      setConfirm(null);
    } catch (err: unknown) {
      alert("Send failed: " + (err instanceof Error ? err.message : err));
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-slate-900">🔔 Follow-ups</h1>
        {emails.length > 0 && (
          <span className="text-sm text-slate-500">{emails.length} sent without reply</span>
        )}
      </div>

      {/* Controls */}
      <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Sent {days}+ days ago
            </label>
            <input type="range" min={1} max={14} value={days}
              onChange={e => setDays(+e.target.value)}
              className="mt-2 w-full accent-indigo-500" />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Max emails: {max}
            </label>
            <input type="range" min={5} max={50} value={max}
              onChange={e => setMax(+e.target.value)}
              className="mt-2 w-full accent-indigo-500" />
          </div>
        </div>
        <button onClick={scan} disabled={loading}
          className="w-full bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60 text-white font-semibold py-2 rounded-lg transition-colors">
          {loading ? "Scanning…" : "Scan Follow-ups"}
        </button>
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </div>

      {emails.length === 0 && !loading && (
        <p className="text-center text-slate-400 text-sm py-8">
          No emails awaiting follow-up (or scan not run yet).
        </p>
      )}

      {emails.map(e => {
        const d = drafts[e.email_id];
        return (
          <div key={e.email_id} className="bg-white rounded-xl border border-slate-200 overflow-hidden">
            <div className="p-4">
              <div className="flex justify-between items-start mb-1">
                <span className="font-semibold text-sm text-slate-800">{e.to.join(", ")}</span>
                <span className="text-xs text-slate-400 shrink-0">{e.date.slice(0, 16)}</span>
              </div>
              <p className="font-semibold text-slate-900 mb-1">{e.subject || "(no subject)"}</p>
              <p className="text-sm text-slate-500 line-clamp-2">{e.snippet}</p>

              {!d && !sentIds.has(e.email_id) && !savedIds.has(e.email_id) && (
                <button onClick={() => generateDraft(e)} disabled={draftLoading[e.email_id]}
                  className="mt-3 px-3 py-1.5 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold disabled:opacity-60">
                  {draftLoading[e.email_id] ? "Generating…" : "✍️ Generate Follow-up"}
                </button>
              )}
            </div>

            {d && !sentIds.has(e.email_id) && !savedIds.has(e.email_id) && (
              <div className="border-t border-slate-100 bg-green-50 p-4 space-y-2">
                <p className="text-xs font-bold text-green-700 uppercase tracking-wide">🤖 Follow-up Draft</p>
                <input
                  className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  value={d.subject}
                  onChange={ev => setDrafts(prev => ({ ...prev, [e.email_id]: { ...d, subject: ev.target.value } }))}
                />
                <textarea rows={4}
                  className="w-full border border-slate-200 rounded-lg px-3 py-1.5 text-sm bg-white resize-none focus:outline-none focus:ring-2 focus:ring-indigo-400"
                  value={d.body}
                  onChange={ev => setDrafts(prev => ({ ...prev, [e.email_id]: { ...d, body: ev.target.value } }))}
                />
                <div className="flex gap-2">
                  <button onClick={() => save(e)}
                    className="px-3 py-1.5 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold">
                    Save Draft
                  </button>
                  <button onClick={() => setConfirm(e.email_id)}
                    className="px-3 py-1.5 bg-green-500 text-white text-sm rounded-lg hover:bg-green-600 font-semibold">
                    📤 Send Now
                  </button>
                </div>
                {confirm === e.email_id && (
                  <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
                    <p className="text-sm text-amber-800 font-medium">
                      ⚠️ Send follow-up to <strong>{e.to.join(", ")}</strong>?
                    </p>
                    <div className="flex gap-2">
                      <button onClick={() => send(e)}
                        className="px-3 py-1 bg-green-500 text-white text-sm rounded-lg font-semibold">
                        ✅ Confirm
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

            {sentIds.has(e.email_id) && (
              <div className="border-t border-slate-100 bg-green-50 px-4 py-3">
                <span className="text-green-600 text-sm font-semibold">📤 Follow-up sent</span>
              </div>
            )}
            {savedIds.has(e.email_id) && (
              <div className="border-t border-slate-100 bg-indigo-50 px-4 py-3">
                <span className="text-indigo-600 text-sm font-semibold">📁 Saved to drafts</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
