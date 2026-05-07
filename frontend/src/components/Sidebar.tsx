"use client";
import { Inbox, PenLine, Bell, History, Settings } from "lucide-react";
import type { Tab } from "@/app/page";
import clsx from "clsx";

const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "inbox",         label: "Inbox",         icon: <Inbox size={18} /> },
  { id: "compose",       label: "Compose",       icon: <PenLine size={18} /> },
  { id: "followups",     label: "Follow-ups",    icon: <Bell size={18} /> },
  { id: "conversations", label: "Conversations", icon: <History size={18} /> },
  { id: "settings",      label: "Settings",      icon: <Settings size={18} /> },
];

export default function Sidebar({
  activeTab,
  onTabChange,
}: {
  activeTab: Tab;
  onTabChange: (t: Tab) => void;
}) {
  return (
    <aside className="w-56 shrink-0 border-r border-slate-200 bg-white flex flex-col">
      {/* Brand */}
      <div className="px-5 py-5 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-indigo-500 flex items-center justify-center text-white text-sm">
            ✉
          </div>
          <div>
            <div className="font-bold text-sm text-slate-900">Email Agent</div>
            <div className="text-xs text-slate-400">AI-powered inbox</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 space-y-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => onTabChange(t.id)}
            className={clsx(
              "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              activeTab === t.id
                ? "bg-indigo-50 text-indigo-600"
                : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </nav>

      <div className="px-5 py-4 border-t border-slate-100 text-xs text-slate-400">
        gpt-4o-mini · OpenAI
      </div>
    </aside>
  );
}
