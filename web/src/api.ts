// Thin client for the LeakTrace API. Same origin in production; Vite forwards these paths in development.

export class ApiError extends Error {
  constructor(public status: number, public code: string, public body: unknown) {
    super(code);
  }
  get mapDown(): boolean {
    return this.status === 503;
  }
}

const TOKEN = "leaktrace.token";
const WHO = "leaktrace.who";

export type Who = { user: string; role: string; tenant: string };

export const session = {
  token(): string | null {
    try { return localStorage.getItem(TOKEN); } catch { return null; }
  },
  who(): Who | null {
    try { const w = localStorage.getItem(WHO); return w ? JSON.parse(w) : null; } catch { return null; }
  },
  save(token: string, who: Who) {
    try { localStorage.setItem(TOKEN, token); localStorage.setItem(WHO, JSON.stringify(who)); } catch { /* private window */ }
  },
  clear() {
    try { localStorage.removeItem(TOKEN); localStorage.removeItem(WHO); } catch { /* ignore */ }
  },
};

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const t = session.token();
  if (t) headers.Authorization = `Bearer ${t}`;
  let res: Response;
  try {
    res = await fetch(path, { method: opts.method || "GET", headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body) });
  } catch {
    throw new ApiError(503, "unreachable", null);
  }
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    if (res.status === 401 && t) session.clear();
    const code = (data && (data.error || data.detail)) || String(res.status);
    throw new ApiError(res.status, typeof code === "string" ? code : JSON.stringify(code), data);
  }
  return data as T;
}

export async function login(tenant: string, username: string, password: string): Promise<Who> {
  const out = await api<{ token: string; role: string; tenant: string }>("/auth/login", {
    method: "POST", body: { tenant, username, password },
  });
  const who = { user: username, role: out.role, tenant: out.tenant };
  session.save(out.token, who);
  return who;
}
