"use client";

import { motion, useReducedMotion } from "framer-motion";
import { cn, pct } from "@/lib/utils";

export interface Prediction {
  probability: number;
  probability_uncalibrated: number;
  threshold: number;
  decision: "above_threshold" | "below_threshold";
  risk_band: "high" | "elevated" | "borderline-low" | "low";
  near_threshold: boolean;
  contributions: { feature: string; label: string; value: number; direction: string }[];
  baseline_probability: number;
  ood_warning: boolean;
  ood_features: string[];
  missing_inputs: string[];
  model_id: string;
  model_version: string;
  disclaimer: string;
  inputs: Record<string, number | null>;
}

export const BAND = {
  high: { label: "High", tone: "danger", color: "var(--danger)" },
  elevated: { label: "Elevated", tone: "warning", color: "var(--warning)" },
  "borderline-low": { label: "Borderline", tone: "warning", color: "var(--warning)" },
  low: { label: "Low", tone: "success", color: "var(--success)" },
} as const;

/** Semicircular gauge with the decision threshold marked. */
export function RiskGauge({ p, threshold, band }: { p: number; threshold: number; band: keyof typeof BAND }) {
  const reduce = useReducedMotion();
  const R = 88;
  const C = Math.PI * R;
  const angle = (v: number) => Math.PI * (1 - v);
  const tx = 110 + R * Math.cos(angle(threshold));
  const ty = 104 - R * Math.sin(angle(threshold));
  const color = BAND[band].color;
  return (
    <figure className="relative mx-auto w-full max-w-[280px]" aria-label={`Calibrated probability ${pct(p)}; threshold ${pct(threshold)}`}>
      <svg viewBox="0 0 220 124" className="w-full overflow-visible">
        <defs>
          <linearGradient id="gauge" x1="0" x2="1">
            <stop offset="0" stopColor="var(--success)" />
            <stop offset="0.5" stopColor="var(--warning)" />
            <stop offset="1" stopColor="var(--danger)" />
          </linearGradient>
        </defs>
        <path d="M22 104a88 88 0 0 1 176 0" fill="none" stroke="var(--surface-3)" strokeWidth="14" strokeLinecap="round" />
        <path d="M22 104a88 88 0 0 1 176 0" fill="none" stroke="url(#gauge)" strokeOpacity="0.18" strokeWidth="14" strokeLinecap="round" />
        <motion.path
          d="M22 104a88 88 0 0 1 176 0"
          fill="none"
          stroke={color}
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={C}
          initial={{ strokeDashoffset: C }}
          animate={{ strokeDashoffset: C * (1 - p) }}
          transition={{ duration: reduce ? 0 : 1.1, ease: [0.22, 1, 0.36, 1] }}
        />
        <line x1={110 + (R - 13) * Math.cos(angle(threshold))} y1={104 - (R - 13) * Math.sin(angle(threshold))} x2={tx + 9 * Math.cos(angle(threshold))} y2={ty - 9 * Math.sin(angle(threshold))} stroke="var(--fg)" strokeWidth="2.5" strokeLinecap="round" />
        <text x={tx + 22 * Math.cos(angle(threshold))} y={ty - 22 * Math.sin(angle(threshold))} textAnchor="middle" fontSize="9" fill="var(--muted)">
          threshold
        </text>
      </svg>
      <figcaption className="absolute inset-x-0 bottom-0 text-center">
        <motion.div
          className="tabular text-[40px] font-semibold leading-none tracking-tight"
          style={{ color }}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: reduce ? 0 : 0.3 }}
        >
          {pct(p)}
        </motion.div>
        <div className="mt-1 text-xs text-muted">calibrated probability</div>
      </figcaption>
    </figure>
  );
}

/** Horizontal diverging bars of per-feature contributions (logit scale). */
export function ContributionBars({ items }: { items: Prediction["contributions"] }) {
  const max = Math.max(...items.map((c) => Math.abs(c.value)), 1e-6);
  return (
    <ul className="space-y-2.5" aria-label="Factors contributing to the estimate">
      {items.map((c, i) => {
        const w = (Math.abs(c.value) / max) * 50;
        const up = c.value > 0;
        return (
          <li key={c.feature} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_3rem] items-center gap-3">
            <span className="truncate text-[13px] text-fg" title={c.label}>
              {c.label}
            </span>
            <div className="relative h-6" role="img" aria-label={`${c.label} ${up ? "increases" : "decreases"} risk by ${Math.abs(c.value).toFixed(2)} log-odds`}>
              <div className="absolute left-1/2 top-0 h-full w-px bg-border-strong" aria-hidden />
              <motion.div
                className={cn("absolute top-1 h-4 rounded-md", up ? "bg-danger/80" : "bg-primary/80")}
                style={up ? { left: "50%" } : { right: "50%" }}
                initial={{ width: 0 }}
                animate={{ width: `${w}%` }}
                transition={{ duration: 0.6, delay: 0.05 * i, ease: "easeOut" }}
              />
            </div>
            <span className={cn("tabular text-right text-[12px] font-medium", up ? "text-danger" : "text-primary")}>
              {up ? "+" : "−"}
              {Math.abs(c.value).toFixed(2)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function explain(pred: Prediction): string[] {
  const ups = pred.contributions.filter((c) => c.value > 0).slice(0, 3).map((c) => c.label.toLowerCase());
  const downs = pred.contributions.filter((c) => c.value < 0).slice(0, 2).map((c) => c.label.toLowerCase());
  const out: string[] = [];
  out.push(
    `The model estimates a ${pct(pred.probability)} probability of angiographic coronary artery disease, ` +
      `${pred.decision === "above_threshold" ? "above" : "below"} the ${pct(pred.threshold)} decision threshold ` +
      `(average across training patients: ${pct(pred.baseline_probability)}).`,
  );
  if (ups.length) out.push(`Factors pushing the estimate up: ${ups.join(", ")}.`);
  if (downs.length) out.push(`Factors pulling it down: ${downs.join(", ")}.`);
  if (pred.near_threshold) out.push("This result is close to the threshold, so small measurement changes could flip the decision.");
  return out;
}
