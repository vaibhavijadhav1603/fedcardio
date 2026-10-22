"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

export const SERIES = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)", "var(--chart-6)"];

/** Recharts needs concrete colours for some props; resolve CSS variables at runtime (theme-aware). */
export function useChartTheme() {
  const { resolvedTheme } = useTheme();
  const [t, setT] = useState({ grid: "#e3e8f0", axis: "#8a97ab", fg: "#0d1526", surface: "#fff" });
  useEffect(() => {
    const s = getComputedStyle(document.documentElement);
    const v = (n: string) => s.getPropertyValue(n).trim();
    setT({ grid: v("--border"), axis: v("--subtle"), fg: v("--fg"), surface: v("--surface") });
  }, [resolvedTheme]);
  return t;
}

export function ChartTooltip({ active, payload, label, fmt = (v: number) => v.toFixed(3), labelFmt }: {
  active?: boolean;
  payload?: { name: string; value: number; color: string }[];
  label?: string | number;
  fmt?: (v: number) => string;
  labelFmt?: (l: string | number) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl border border-border bg-surface px-3 py-2 text-xs shadow-card">
      <div className="mb-1 font-medium text-fg">{labelFmt ? labelFmt(label ?? "") : label}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2 text-muted">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="flex-1">{p.name}</span>
          <span className="tabular font-medium text-fg">{p.value == null ? "—" : fmt(p.value)}</span>
        </div>
      ))}
    </div>
  );
}
