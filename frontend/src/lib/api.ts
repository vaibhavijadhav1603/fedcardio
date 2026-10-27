// Minimal API client. The access token lives in memory only; the refresh token is an
// httpOnly, SameSite=strict cookie scoped to /api/auth that JavaScript cannot read.

export type Role = "platform_admin" | "hospital_admin" | "clinician" | "data_scientist" | "auditor";

export interface Me {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  hospital_id: number | null;
  hospital_name: string | null;
  hospital_code: string | null;
  mfa_enabled: boolean;
  must_change_password: boolean;
  permissions: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onUnauthorized: (() => void) | null = null;

export const setAccessToken = (t: string | null) => {
  accessToken = t;
};
export const setOnUnauthorized = (fn: () => void) => {
  onUnauthorized = fn;
};

export async function refreshSession(): Promise<{ access_token: string; user: Me } | null> {
  const r = await fetch("/api/auth/refresh", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Requested-With": "fedcardio" },
  });
  if (!r.ok) return null;
  const data = await r.json();
  accessToken = data.access_token;
  return data;
}

function detail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => (e as { msg?: string }).msg ?? "invalid input").join("; ");
  }
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const r = await fetch(`/api${path}`, { ...init, headers, body, credentials: "same-origin" });
  if (r.status === 401 && retry && !path.startsWith("/auth/")) {
    refreshing ??= refreshSession().then((x) => !!x).finally(() => (refreshing = null));
    if (await refreshing) return api<T>(path, init, false);
    onUnauthorized?.();
  }
  if (!r.ok) {
    let b: unknown = null;
    try {
      b = await r.json();
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(r.status, detail(b, `${r.status} ${r.statusText}`));
  }
  const ct = r.headers.get("content-type") ?? "";
  return (ct.includes("application/json") ? r.json() : r.text()) as Promise<T>;
}

export async function download(path: string, filename: string) {
  const headers = new Headers();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const r = await fetch(`/api${path}`, { headers });
  if (!r.ok) throw new ApiError(r.status, "download failed");
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}
