"use client";
import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import InboxTab from "@/components/InboxTab";
import ComposeTab from "@/components/ComposeTab";
import FollowupsTab from "@/components/FollowupsTab";
import ConversationsTab from "@/components/ConversationsTab";
import SettingsTab from "@/components/SettingsTab";

export type Tab = "inbox" | "compose" | "followups" | "conversations" | "settings";

export default function Home() {
  const [tab, setTab] = useState<Tab>("inbox");

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar activeTab={tab} onTabChange={setTab} />
      <main className="flex-1 overflow-y-auto p-6">
        {tab === "inbox"         && <InboxTab />}
        {tab === "compose"       && <ComposeTab />}
        {tab === "followups"     && <FollowupsTab />}
        {tab === "conversations" && <ConversationsTab />}
        {tab === "settings"      && <SettingsTab />}
      </main>
    </div>
  );
}
