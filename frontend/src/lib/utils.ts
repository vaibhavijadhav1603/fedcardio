import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const pct = (v: number | null | undefined, d = 0) =>
  v == null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(d)}%`;

export const num = (v: number | null | undefined, d = 3) =>
  v == null || Number.isNaN(v) ? "—" : v.toFixed(d);

export function bytes(n: number | null | undefined) {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${u[i]}`;
}

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
