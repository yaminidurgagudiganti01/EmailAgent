"use client";
import { useEffect, useState } from "react";
import { api, type Rule, type KbEntry } from "@/lib/api";
import clsx from "clsx";

type RuleType = "sender" | "domain" | "category";

const RULE_TYPES: { value: RuleType; label: string; placeholder: string }[] = [
  { value: "sender",   label: "Sender email",  placeholder: "e.g. noreply@example.com" },
  { value: "domain",   label: "Domain",        placeholder: "e.g. marketing.example.com" },
  { value: "category", label: "Category",      placeholder: "e.g. newsletter" },
];

const RULE_BADGE: Record<string, string> = {
  sender:   "bg-blue-100 text-blue-700",
  domain:   "bg-purple-100 text-purple-700",
  category: "bg-amber-100 text-amber-700",
};

const INPUT = "w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400";

export default function SettingsTab() {
  const [rules, setRules]         = useState<Rule[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState("");
  const [ruleType, setRuleType]   = useState<RuleType>("sender");
  const [ruleValue, setRuleValue] = useState("");
  const [adding, setAdding]       = useState(false);
  const [stats, setStats]         = useState<Record<string, number> | null>(null);
  const [health, setHealth]       = useState<{ status: string } | null>(null);

  // Style learning
  const [styleProfile, setStyle]  = useState<string | null>(null);
  const [styleLoading, setSL]     = useState(false);

  // Knowledge base
  const [kbEntries, setKb]        = useState<KbEntry[]>([]);
  const [kbTitle, setKbTitle]     = useState("");
  const [kbContent, setKbContent] = useState("");
  const [kbAdding, setKbAdding]   = useState(false);

  useEffect(() => {
    Promise.all([
      api.getRules().then(r => setRules(r.rules)),
      api.stats().then(s => setStats(s as Record<string, number>)),
      api.health().then(h => setHealth(h as { status: string })),
      api.getStyle().then(r => setStyle(r.profile)),
      api.getKb().then(r => setKb(r.entries)),
    ])
      .catch(e => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, []);

  async function addRule() {
    if (!ruleValue.trim()) return;
    setAdding(true);
    try {
      await api.addRule({ rule_type: ruleType, value: ruleValue.trim() });
      const r = await api.getRules();
      setRules(r.rules);
      setRuleValue("");
    } catch (e: unknown) {
      alert("Failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setAdding(false);
    }
  }

  async function deleteRule(id: number) {
    try {
      await api.deleteRule(id);
      setRules(prev => prev.filter(r => r.id !== id));
    } catch (e: unknown) {
      alert("Delete failed: " + (e instanceof Error ? e.message : e));
    }
  }

  async function learnStyle() {
    setSL(true);
    try {
      const res = await api.learnStyle();
      setStyle(res.profile);
      alert(`Style learned from ${res.emails_analysed} sent emails!`);
    } catch (e: unknown) {
      alert("Failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setSL(false);
    }
  }

  async function addKb() {
    if (!kbTitle.trim() || !kbContent.trim()) return;
    setKbAdding(true);
    try {
      await api.addKb({ title: kbTitle.trim(), content: kbContent.trim() });
      const r = await api.getKb();
      setKb(r.entries);
      setKbTitle(""); setKbContent("");
    } catch (e: unknown) {
      alert("Failed: " + (e instanceof Error ? e.message : e));
    } finally {
      setKbAdding(false);
    }
  }

  async function deleteKb(id: number) {
    try {
      await api.deleteKb(id);
      setKb(prev => prev.filter(e => e.id !== id));
    } catch (e: unknown) {
      alert("Delete failed: " + (e instanceof Error ? e.message : e));
    }
  }

  const placeholder = RULE_TYPES.find(r => r.value === ruleType)?.placeholder ?? "";

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-bold text-slate-900">⚙️ Settings</h1>

      {/* System Status */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
        <h2 className="font-semibold text-slate-800">System Status</h2>
        {loading ? (
          <p className="text-slate-400 text-sm">Loading…</p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className={clsx("w-2 h-2 rounded-full", health?.status === "ok" ? "bg-green-500" : "bg-red-500")} />
              <span className="text-sm text-slate-700 font-medium">
                API: {health?.status ?? "unknown"}
              </span>
            </div>
            {stats && (
              <div className="grid grid-cols-3 gap-3">
                {Object.entries(stats).map(([k, v]) => (
                  <div key={k} className="bg-slate-50 rounded-lg p-3 text-center">
                    <p className="text-2xl font-bold text-indigo-600">{v}</p>
                    <p className="text-xs text-slate-500 mt-0.5 capitalize">{k.replace(/_/g, " ")}</p>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </div>

      {/* Style Learning */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-semibold text-slate-800">🧠 Writing Style</h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Analyses your sent emails (original only, not replies) so the AI matches your tone and phrasing.
            </p>
          </div>
          <button onClick={learnStyle} disabled={styleLoading}
            className="shrink-0 px-3 py-1.5 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold disabled:opacity-60">
            {styleLoading ? "Analysing…" : styleProfile ? "Re-learn" : "Learn My Style"}
          </button>
        </div>
        {styleProfile ? (
          <div className="bg-indigo-50 rounded-lg p-3">
            <p className="text-xs font-bold text-indigo-600 uppercase tracking-wide mb-2">Learned Style</p>
            <pre className="text-xs text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">{styleProfile}</pre>
          </div>
        ) : (
          <p className="text-sm text-slate-400 italic">No style profile yet — click "Learn My Style" to analyse your sent emails.</p>
        )}
      </div>

      {/* Knowledge Base */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
        <div>
          <h2 className="font-semibold text-slate-800">📚 Knowledge Base</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Facts, policies, or templates the AI can draw from when drafting emails.
          </p>
        </div>

        <div className="space-y-2">
          <input value={kbTitle} onChange={e => setKbTitle(e.target.value)}
            placeholder="Title (e.g. Working hours, Pricing, FAQ)"
            className={INPUT} />
          <textarea value={kbContent} onChange={e => setKbContent(e.target.value)}
            placeholder="Content the AI should know…" rows={3}
            className={`${INPUT} resize-none`} />
          <button onClick={addKb} disabled={kbAdding || !kbTitle.trim() || !kbContent.trim()}
            className="px-4 py-2 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold disabled:opacity-60">
            {kbAdding ? "Adding…" : "Add Entry"}
          </button>
        </div>

        {kbEntries.length === 0 ? (
          <p className="text-slate-400 text-sm text-center py-2">No knowledge base entries yet.</p>
        ) : (
          <div className="space-y-2">
            {kbEntries.map(e => (
              <div key={e.id} className="bg-slate-50 rounded-lg p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm font-semibold text-slate-800">{e.title}</span>
                  <button onClick={() => deleteKb(e.id)}
                    className="text-red-400 hover:text-red-600 text-xs px-2 py-0.5 rounded hover:bg-red-50">
                    Remove
                  </button>
                </div>
                <p className="text-xs text-slate-500 line-clamp-2">{e.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Exclude Rules */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
        <div>
          <h2 className="font-semibold text-slate-800">🚫 Exclude Rules</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Emails matching these rules will be skipped by the agent.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <select value={ruleType} onChange={e => setRuleType(e.target.value as RuleType)}
            className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400">
            {RULE_TYPES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
          <input value={ruleValue} onChange={e => setRuleValue(e.target.value)}
            placeholder={placeholder}
            onKeyDown={e => e.key === "Enter" && addRule()}
            className="flex-1 min-w-40 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400" />
          <button onClick={addRule} disabled={adding || !ruleValue.trim()}
            className="px-4 py-2 bg-indigo-500 text-white text-sm rounded-lg hover:bg-indigo-600 font-semibold disabled:opacity-60">
            {adding ? "Adding…" : "Add Rule"}
          </button>
        </div>
        {rules.length === 0 ? (
          <p className="text-slate-400 text-sm text-center py-2">No exclude rules configured.</p>
        ) : (
          <div className="space-y-2">
            {rules.map(r => (
              <div key={r.id} className="flex items-center gap-2 bg-slate-50 rounded-lg px-3 py-2">
                <span className={clsx("text-xs px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide shrink-0",
                  RULE_BADGE[r.rule_type] ?? "bg-slate-100 text-slate-600")}>
                  {r.rule_type}
                </span>
                <span className="text-sm text-slate-700 flex-1 font-mono">{r.value}</span>
                <span className="text-xs text-slate-400 shrink-0">{r.created_at.slice(0, 10)}</span>
                <button onClick={() => deleteRule(r.id)}
                  className="text-red-400 hover:text-red-600 text-xs px-2 py-1 rounded hover:bg-red-50">
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* About */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-1">
        <h2 className="font-semibold text-slate-800">About</h2>
        <p className="text-sm text-slate-500">Email Agent — AI-powered inbox management</p>
        <p className="text-xs text-slate-400">Powered by gpt-4o-mini · Gmail API · LangGraph</p>
      </div>
    </div>
  );
}
