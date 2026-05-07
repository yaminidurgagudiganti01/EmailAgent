"use client";
import { useEffect, useState } from "react";
import { api, type LogEntry } from "@/lib/api";
import clsx from "clsx";

const PRIORITY_COLOR: Record<string, string> = {
  high:   "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low:    "bg-slate-100 text-slate-600",
};

const CATEGORY_COLOR: Record<string, string> = {
  reply_needed:    "bg-green-100 text-green-700",
  meeting:         "bg-blue-100 text-blue-700",
  action_required: "bg-amber-100 text-amber-700",
  fyi:             "bg-slate-100 text-slate-600",
  newsletter:      "bg-purple-100 text-purple-700",
  spam:            "bg-red-100 text-red-700",
};

export default function ConversationsTab() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState("");
  const [filter, setFilter]   = useState<"all" | "sent" | "drafted">("all");

  useEffect(() => {
    api.conversations(200)
      .then(r => setEntries(r.entries))
      .catch(e => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  const visible = entries.filter(e => {
    if (filter === "sent")    return e.sent;
    if (filter === "drafted") return !!e.draft_id && !e.sent;
    return true;
  });

  const sentCount    = entries.filter(e => e.sent).length;
  const draftedCount = entries.filter(e => e.draft_id && !e.sent).length;

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-slate-900">📋 Conversations</h1>
        {!loading && (
          <div className="flex gap-2 text-sm text-slate-500">
            <span>{entries.length} total</span>
            <span>·</span>
            <span>{sentCount} sent</span>
            <span>·</span>
            <span>{draftedCount} drafted</span>
          </div>
        )}
      </div>

      {/* Filter pills */}
      <div className="flex gap-2">
        {(["all", "sent", "drafted"] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={clsx(
              "px-3 py-1 rounded-full text-sm font-medium transition-colors",
              filter === f
                ? "bg-indigo-500 text-white"
                : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"
            )}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {loading && <p className="text-slate-400 text-sm text-center py-8">Loading…</p>}
      {error   && <p className="text-red-500 text-sm">{error}</p>}

      {!loading && visible.length === 0 && (
        <p className="text-center text-slate-400 text-sm py-8">No emails found.</p>
      )}

      <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100 overflow-hidden">
        {visible.map(e => (
          <div key={e.email_id} className="px-4 py-3 flex items-start gap-4 hover:bg-slate-50 transition-colors">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                <span className="font-semibold text-sm text-slate-800 truncate">{e.from_addr}</span>
                <span className={clsx("text-xs px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide shrink-0",
                  CATEGORY_COLOR[e.category] ?? "bg-slate-100 text-slate-600")}>
                  {e.category.replace("_", " ")}
                </span>
                <span className={clsx("text-xs px-2 py-0.5 rounded-full shrink-0",
                  PRIORITY_COLOR[e.priority] ?? "bg-slate-100 text-slate-600")}>
                  {e.priority}
                </span>
              </div>
              <p className="text-sm text-slate-700 truncate">{e.subject || "(no subject)"}</p>
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              <span className="text-xs text-slate-400">{e.logged_at.slice(0, 16)}</span>
              <div className="flex gap-1">
                {e.sent && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">
                    Sent
                  </span>
                )}
                {e.draft_id && !e.sent && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 font-medium">
                    Drafted
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
