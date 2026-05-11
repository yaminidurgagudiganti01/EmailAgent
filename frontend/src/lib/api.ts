const BASE = "/api";

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  health:               ()                                        => req("GET",  "/health"),
  stats:                ()                                        => req("GET",  "/stats"),
  run:                  (body: RunRequest)                        => req<RunResponse>("POST", "/run", body),
  saveDraft:            (body: SendRequest)                       => req<{draft_id: string}>("POST", "/drafts/save", body),
  sendEmail:            (body: SendRequest)                       => req<{message_id: string}>("POST", "/emails/send", body),
  compose:              (body: ComposeRequest)                    => req<DraftData>("POST", "/compose", body),
  scanFollowups:        (body: {days:number; max_emails:number})  => req<FollowupResponse>("POST", "/followups/scan", body),
  updateFollowupStatus: (thread_id: string, status: "sent" | "dismissed") =>
                          req("PATCH", `/followups/${encodeURIComponent(thread_id)}`, { status }),
  conversations:        (limit=100)                               => req<{entries: LogEntry[]}>("GET", `/conversations?limit=${limit}`),
  getRules:             ()                                        => req<{rules: Rule[]}>("GET", "/rules"),
  addRule:              (body: {rule_type:string; value:string})  => req("POST", "/rules", body),
  deleteRule:           (id: number)                              => req("DELETE", `/rules/${id}`),
  getStyle:             ()                                        => req<{profile: string | null}>("GET", "/style"),
  learnStyle:           ()                                        => req<{profile: string; emails_analysed: number}>("POST", "/style/learn"),
  getKb:                ()                                        => req<{entries: KbEntry[]}>("GET", "/kb"),
  addKb:                (body: {title: string; content: string})  => req("POST", "/kb", body),
  deleteKb:             (id: number)                              => req("DELETE", `/kb/${id}`),
};

// ── Types ─────────────────────────────────────────────────────────────────────

export interface RunRequest {
  query: string;
  max_emails: number;
  apply_labels: boolean;
  mark_as_read: boolean;
}

export interface EmailResult {
  email_id: string;
  from_addr: string;
  subject: string;
  date: string;
  snippet: string;
  category: string;
  priority: "high" | "medium" | "low";
  confidence: number;
  needs_review: boolean;
  reasoning: string;
  suggested_action: string;
  excluded: boolean;
  draft: DraftData | null;
  error?: string;
}

export interface DraftData {
  to: string[];
  cc: string[];
  subject: string;
  body: string;
  thread_id?: string | null;
}

export interface RunResponse {
  count: number;
  emails: EmailResult[];
}

export interface SendRequest {
  to: string[];
  subject: string;
  body: string;
  cc?: string[];
  thread_id?: string | null;
  email_id?: string | null;
}

export interface ComposeRequest {
  to: string;
  subject: string;
  context: string;
}

export interface FollowupEmail {
  email_id: string;
  to: string[];
  subject: string;
  date: string;
  snippet: string;
  thread_id: string | null;
}

export interface FollowupResponse {
  count: number;
  emails: FollowupEmail[];
}

export interface LogEntry {
  email_id: string;
  from_addr: string;
  subject: string;
  category: string;
  priority: string;
  draft_id: string | null;
  sent: boolean;
  logged_at: string;
}

export interface Rule {
  id: number;
  rule_type: string;
  value: string;
  created_at: string;
}

export interface KbEntry {
  id: number;
  title: string;
  content: string;
  created_at: string;
}
