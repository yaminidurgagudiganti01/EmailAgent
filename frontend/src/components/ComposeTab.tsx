"use client";
import { useState } from "react";
import { api, type DraftData, type SendRequest } from "@/lib/api";

type Stage = "form" | "draft" | "sent";

const INPUT = "w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400";

export default function ComposeTab() {
  const [to, setTo]           = useState("");
  const [subject, setSubject] = useState("");
  const [context, setContext] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [draft, setDraft]     = useState<DraftData | null>(null);
  const [editSubject, setES]  = useState("");
  const [editBody, setEB]     = useState("");
  const [stage, setStage]     = useState<Stage>("form");
  const [confirm, setConfirm] = useState(false);

  async function generate() {
    if (!to.trim() || !subject.trim()) { setError("To and Subject are required."); return; }
    setLoading(true); setError("");
    try {
      const d = await api.compose({ to: to.trim(), subject: subject.trim(), context: context.trim() });
      setDraft(d);
      setES(d.subject);
      setEB(d.body);
      setStage("draft");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function saveDraft() {
    if (!draft) return;
    try {
      await api.saveDraft({ to: draft.to, subject: editSubject, body: editBody });
      setStage("sent");
    } catch (e: unknown) {
      alert("Save failed: " + (e instanceof Error ? e.message : e));
    }
  }

  async function send() {
    if (!draft) return;
    try {
      const payload: SendRequest = { to: draft.to, subject: editSubject, body: editBody };
      if (draft.cc?.length) payload.cc = draft.cc;
      await api.sendEmail(payload);
      setConfirm(false);
      setStage("sent");
    } catch (e: unknown) {
      alert("Send failed: " + (e instanceof Error ? e.message : e));
    }
  }

  function reset() {
    setTo(""); setSubject(""); setContext(""); setDraft(null);
    setES(""); setEB(""); setStage("form"); setError(""); setConfirm(false);
  }

  if (stage === "sent") return (
    <div className="max-w-2xl mx-auto">
      <div className="bg-green-50 border border-green-200 rounded-xl p-8 text-center space-y-3 mt-6">
        <p className="text-2xl">📤</p>
        <p className="font-semibold text-green-700">Email sent (or saved to drafts)!</p>
        <button onClick={reset}
          className="px-4 py-2 bg-indigo-500 text-white rounded-lg text-sm font-semibold hover:bg-indigo-600">
          Compose another
        </button>
      </div>
    </div>
  );

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-bold text-slate-900">✏️ Compose</h1>

      {stage === "form" ? (
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">To</label>
            <input value={to} onChange={e => setTo(e.target.value)} placeholder="recipient@example.com"
              className={`mt-1 ${INPUT}`} />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Subject</label>
            <input value={subject} onChange={e => setSubject(e.target.value)} placeholder="Email subject…"
              className={`mt-1 ${INPUT}`} />
          </div>
          <div>
            <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Context / instructions (optional)
            </label>
            <textarea value={context} onChange={e => setContext(e.target.value)} rows={4}
              placeholder="Describe what you want to say…"
              className={`mt-1 ${INPUT} resize-none`} />
          </div>
          {error && <p className="text-red-500 text-sm">{error}</p>}
          <button onClick={generate} disabled={loading}
            className="w-full bg-indigo-500 hover:bg-indigo-600 disabled:opacity-60 text-white font-semibold py-2 rounded-lg transition-colors">
            {loading ? "Generating draft…" : "Generate AI Draft"}
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
            <p className="text-xs font-bold text-indigo-600 uppercase tracking-wide">🤖 AI Draft</p>
            <p className="text-sm text-slate-500">
              To: <span className="text-slate-800">{draft?.to.join(", ")}</span>
            </p>
            <div>
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Subject</label>
              <input value={editSubject} onChange={e => setES(e.target.value)}
                className={`mt-1 ${INPUT}`} />
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-500 uppercase tracking-wide">Body</label>
              <textarea value={editBody} onChange={e => setEB(e.target.value)} rows={10}
                className={`mt-1 ${INPUT} resize-none`} />
            </div>
            <div className="flex gap-2 pt-1">
              <button onClick={saveDraft}
                className="px-4 py-2 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold">
                Save to Drafts
              </button>
              <button onClick={() => setConfirm(true)}
                className="px-4 py-2 bg-green-500 text-white text-sm rounded-lg hover:bg-green-600 font-semibold">
                📤 Send Now
              </button>
              <button onClick={() => setStage("form")}
                className="px-4 py-2 bg-slate-100 text-slate-600 text-sm rounded-lg hover:bg-slate-200">
                Back
              </button>
            </div>
          </div>

          {confirm && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3">
              <p className="text-sm text-amber-800 font-medium">
                ⚠️ Send to <strong>{draft?.to.join(", ")}</strong>? This cannot be undone.
              </p>
              <div className="flex gap-2">
                <button onClick={send}
                  className="px-3 py-1.5 bg-green-500 text-white text-sm rounded-lg font-semibold">
                  ✅ Confirm Send
                </button>
                <button onClick={() => setConfirm(false)}
                  className="px-3 py-1.5 bg-slate-200 text-slate-700 text-sm rounded-lg">
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
