"use client";

import { motion, useReducedMotion } from "framer-motion";

export function Logo({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--primary)" />
          <stop offset="1" stopColor="var(--accent)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#lg)" />
      <path
        d="M16 23.5s-7-4.2-7-9.2A3.8 3.8 0 0 1 16 12a3.8 3.8 0 0 1 7 2.3c0 5-7 9.2-7 9.2Z"
        fill="none"
        stroke="white"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="M10.5 16h3l1.3-2.4 2.2 4.6 1.3-2.2h3.2" fill="none" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Animated illustration: four hospitals send encrypted model updates to an aggregator. */
export function FederationArt() {
  const reduce = useReducedMotion();
  const nodes = [
    { x: 70, y: 70, label: "Cleveland" },
    { x: 330, y: 70, label: "Budapest" },
    { x: 70, y: 290, label: "Zürich" },
    { x: 330, y: 290, label: "Long Beach" },
  ];
  const c = { x: 200, y: 180 };
  return (
    <svg viewBox="0 0 400 360" className="w-full max-w-md" role="img" aria-label="Four hospitals train a shared model without sharing patient data">
      {nodes.map((n, i) => (
        <g key={n.label}>
          <line x1={n.x} y1={n.y} x2={c.x} y2={c.y} stroke="white" strokeOpacity="0.25" strokeDasharray="4 6" />
          {!reduce && (
            <motion.circle
              r="4"
              fill="white"
              initial={{ cx: n.x, cy: n.y, opacity: 0 }}
              animate={{ cx: [n.x, c.x, n.x], cy: [n.y, c.y, n.y], opacity: [0, 1, 0] }}
              transition={{ duration: 3.2, repeat: Infinity, delay: i * 0.8, ease: "easeInOut" }}
            />
          )}
          <rect x={n.x - 44} y={n.y - 26} width="88" height="52" rx="14" fill="white" fillOpacity="0.12" stroke="white" strokeOpacity="0.35" />
          <path
            d={`M${n.x - 6} ${n.y - 10}h12M${n.x} ${n.y - 16}v12`}
            stroke="white"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
          <text x={n.x} y={n.y + 15} textAnchor="middle" fill="white" fontSize="11" fontWeight="500" opacity="0.9">
            {n.label}
          </text>
        </g>
      ))}
      <motion.circle
        cx={c.x}
        cy={c.y}
        r="44"
        fill="white"
        fillOpacity="0.08"
        stroke="white"
        strokeOpacity="0.4"
        animate={reduce ? undefined : { r: [42, 48, 42] }}
        transition={{ duration: 3.2, repeat: Infinity }}
      />
      <circle cx={c.x} cy={c.y} r="30" fill="white" fillOpacity="0.95" />
      <path
        d={`M${c.x - 8} ${c.y - 2}v-4a8 8 0 0 1 16 0v4`}
        fill="none"
        stroke="var(--primary)"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <rect x={c.x - 11} y={c.y - 2} width="22" height="15" rx="4" fill="var(--primary)" />
    </svg>
  );
}
