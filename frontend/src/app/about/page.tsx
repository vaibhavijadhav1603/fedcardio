"use client";

import { motion } from "framer-motion";
import {
  Activity, ArrowLeft, ArrowRight, Building2, CheckCircle2, Database, EyeOff, FileWarning, FlaskConical, Gauge, Hospital, KeyRound,
  Link2, Lock, ScrollText, ShieldCheck, Shuffle, Sparkles, Stethoscope, Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { Logo } from "@/components/brand";
import { Button } from "@/components/ui";

// One-page infographic of the whole project, reachable from the role launcher.

const fade = {
  initial: { opacity: 0, y: 14 },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, margin: "-60px" },
  transition: { duration: 0.45, ease: "easeOut" as const },
};

function Section({ n, title, sub, children }: { n: number; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <motion.section {...fade} className="mt-14">
      <div className="mb-5 flex items-start gap-3">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary text-sm font-semibold text-primary-fg">{n}</span>
        <div>
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {sub && <p className="mt-0.5 text-sm text-muted">{sub}</p>}
        </div>
      </div>
      {children}
    </motion.section>
  );
}

function Tile({ icon: Icon, title, children, tone = "primary" }: { icon: typeof Lock; title: string; children: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <span className="mb-3 grid size-10 place-items-center rounded-xl text-white" style={{ background: `var(--${tone})` }}>
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="text-[15px] font-semibold">{title}</div>
      <div className="mt-1 text-[13.5px] leading-relaxed text-muted">{children}</div>
    </div>
  );
}

const SITES = [
  { x: 110, y: 70, name: "Cleveland", n: 303 },
  { x: 530, y: 70, name: "Hungary", n: 294 },
  { x: 110, y: 290, name: "Switzerland", n: 123 },
  { x: 530, y: 290, name: "VA Long Beach", n: 200 },
];

function FederationDiagram() {
  const cx = 320, cy = 180;
  return (
    <svg viewBox="0 0 640 360" className="h-auto w-full" role="img"
      aria-label="Four hospitals each keep their data and exchange only model updates with a central aggregator">
      <defs>
        <marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--primary)" />
        </marker>
      </defs>
      {SITES.map((s, i) => {
        const path = `M${s.x},${s.y} L${cx},${cy}`;
        return (
          <g key={s.name}>
            <path d={path} stroke="var(--border-strong)" strokeWidth="2" strokeDasharray="6 6" fill="none" />
            {/* encrypted update travelling to the server */}
            <circle r="6" fill="var(--accent)">
              <animateMotion dur="2.6s" begin={`${i * 0.4}s`} repeatCount="indefinite" path={path} />
            </circle>
            {/* new global model travelling back */}
            <circle r="5" fill="var(--primary)">
              <animateMotion dur="2.6s" begin={`${1.3 + i * 0.4}s`} repeatCount="indefinite" path={`M${cx},${cy} L${s.x},${s.y}`} />
            </circle>
          </g>
        );
      })}
      {/* aggregator */}
      <circle cx={cx} cy={cy} r="54" fill="var(--primary-soft)" stroke="var(--primary)" strokeWidth="2" />
      <text x={cx} y={cy - 6} textAnchor="middle" fontSize="15" fontWeight="600" fill="var(--fg)">Aggregator</text>
      <text x={cx} y={cy + 13} textAnchor="middle" fontSize="11" fill="var(--muted)">combines updates</text>
      <text x={cx} y={cy + 27} textAnchor="middle" fontSize="11" fill="var(--muted)">sees no patient</text>
      {SITES.map((s) => (
        <g key={s.name + "box"}>
          <rect x={s.x - 78} y={s.y - 34} width="156" height="68" rx="14" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="1.5" />
          <text x={s.x - 62} y={s.y - 8} fontSize="14" fontWeight="600" fill="var(--fg)">{s.name}</text>
          <text x={s.x - 62} y={s.y + 12} fontSize="11.5" fill="var(--muted)">{s.n} patients</text>
          <text x={s.x - 62} y={s.y + 26} fontSize="10.5" fill="var(--success)">🔒 data stays here</text>
        </g>
      ))}
    </svg>
  );
}

function Stat({ value, label, sub, tone = "primary" }: { value: string; label: string; sub: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <div className="tabular text-3xl font-semibold tracking-tight" style={{ color: `var(--${tone})` }}>{value}</div>
      <div className="mt-1 text-[14px] font-semibold">{label}</div>
      <div className="mt-0.5 text-[12.5px] leading-relaxed text-muted">{sub}</div>
    </div>
  );
}

export default function AboutPage() {
  const router = useRouter();
  const back = () => (window.history.length > 1 ? router.back() : router.push("/launcher"));
  return (
    <main className="min-h-dvh bg-bg pb-20">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo className="size-8" />
            <span className="font-semibold tracking-tight">How FedCardio works</span>
          </div>
          <Button variant="secondary" size="sm" onClick={back}><ArrowLeft /> Back</Button>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {/* hero: the crux */}
        <motion.div {...fade} className="relative mt-8 overflow-hidden rounded-3xl p-8 text-white sm:p-12"
          style={{ background: "linear-gradient(135deg, #0b4f4a 0%, #0f766e 45%, #3730a3 100%)" }}>
          <div className="bg-grid absolute inset-0 opacity-20" aria-hidden />
          <div className="relative max-w-3xl">
            <div className="text-xs font-semibold uppercase tracking-widest text-teal-200">The crux</div>
            <h1 className="mt-2 text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
              Hospitals train one heart-disease model together, without ever sharing a patient record.
            </h1>
            <p className="mt-4 text-[15px] leading-relaxed text-white/85">
              The model travels to the data, not the data to the model. Only encrypted, privacy-protected model updates leave
              each hospital, and doctors get an explained risk score from the shared model.
            </p>
            <div className="mt-6 flex flex-wrap gap-2 text-[12.5px]">
              {["Federated learning", "Homomorphic encryption", "Secure aggregation", "Differential privacy", "Explainable risk", "Consent-based sharing", "Tamper-proof audit"].map((t) => (
                <span key={t} className="rounded-full bg-white/10 px-3 py-1 ring-1 ring-white/20">{t}</span>
              ))}
            </div>
          </div>
        </motion.div>

        <Section n={1} title="The problem" sub="Why hospitals can't simply pool their data.">
          <div className="grid gap-4 md:grid-cols-3">
            <Tile icon={Database} title="Data is split across hospitals" tone="chart-1">
              Each hospital sees only its own patients: from 123 to 303 here. Too few to train a reliable model alone.
            </Tile>
            <Tile icon={Lock} title="Records can't leave the hospital" tone="danger">
              Privacy law and patient trust forbid sending medical records to a central server.
            </Tile>
            <Tile icon={FileWarning} title="The base paper had gaps" tone="warning">
              Re-implementing Sharma et al. (2026) revealed 11 problems, including a privacy method with no formal guarantee.
            </Tile>
          </div>
        </Section>

        <Section n={2} title="The idea: federated learning" sub="Send the model to the data. Only the lesson learned travels back.">
          <div className="grid items-center gap-6 rounded-3xl border border-border bg-surface p-4 sm:p-6 lg:grid-cols-[1.4fr_1fr]">
            <FederationDiagram />
            <ol className="space-y-4">
              {[
                ["Send", "The aggregator sends the same starting model to every hospital."],
                ["Train locally", "Each hospital improves it on its own patients. Records never move."],
                ["Return updates only", "Each sends back only its model changes, encrypted or masked."],
                ["Combine and repeat", "The aggregator averages the updates into a better model, for 20+ rounds."],
                ["Use it for their own patients", "The finished model goes back to every hospital, where clinicians use it to assess their own patients' heart-disease risk. They train together and each benefits."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary-soft text-[13px] font-semibold text-primary">{i + 1}</span>
                  <div>
                    <div className="text-[14px] font-semibold">{t}</div>
                    <div className="text-[13px] text-muted">{d}</div>
                  </div>
                </li>
              ))}
              <li className="flex items-center gap-4 pt-1 text-[12px] text-muted">
                <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: "var(--accent)" }} /> update</span>
                <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full" style={{ background: "var(--primary)" }} /> new model</span>
              </li>
            </ol>
          </div>
          <p className="mt-3 text-[13px] text-muted">
            Algorithms: <b className="text-fg">FedAvg</b> (average), <b className="text-fg">FedProx</b> (limits drift) and <b className="text-fg">SCAFFOLD</b> (corrects drift when hospitals&apos; patients differ a lot).
          </p>
        </Section>

        <Section n={3} title="Three privacy shields" sub="Even model updates can leak a patient, so each one can be protected.">
          <div className="grid gap-4 md:grid-cols-3">
            <Tile icon={KeyRound} title="Homomorphic encryption (CKKS)" tone="chart-2">
              Updates are encrypted; the aggregator adds them up <b>without being able to read them</b>. Same accuracy, larger uploads.
            </Tile>
            <Tile icon={Shuffle} title="Secure aggregation" tone="chart-3">
              Each hospital&apos;s update is masked with random noise that cancels out in the sum. Only the total is visible.
            </Tile>
            <Tile icon={EyeOff} title="Differential privacy (DP-SGD)" tone="chart-4">
              Measured noise means no single patient can be inferred, even from the final model. Budget: ε (smaller = more private).
            </Tile>
          </div>
        </Section>

        <Section n={4} title="From training to the doctor" sub="How a model reaches the clinic.">
          <div className="grid items-stretch gap-3 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
            {[
              { icon: FlaskConical, t: "Train", d: "Data scientist launches a federated job across the hospitals." },
              { icon: CheckCircle2, t: "Register", d: "A good model is registered as a candidate (staging)." },
              { icon: ShieldCheck, t: "Promote", d: "Platform admin promotes it to production (or rolls back)." },
              { icon: Stethoscope, t: "Use", d: "Clinicians get risk predictions from the production model." },
            ].flatMap((s, i, a) => {
              const card = (
                <div key={s.t} className="rounded-2xl border border-border bg-surface p-4">
                  <s.icon className="mb-2 size-5 text-primary" aria-hidden />
                  <div className="text-[14px] font-semibold">{s.t}</div>
                  <div className="text-[13px] text-muted">{s.d}</div>
                </div>
              );
              return i < a.length - 1
                ? [card, <ArrowRight key={s.t + "a"} className="hidden size-5 self-center text-subtle lg:block" aria-hidden />]
                : [card];
            })}
          </div>
          <div className="mt-4 grid gap-4 rounded-3xl border border-border bg-surface p-5 md:grid-cols-[auto_1fr] md:items-center">
            <div className="flex items-center gap-3">
              <span className="grid size-12 place-items-center rounded-2xl bg-primary-soft text-primary"><Gauge className="size-6" aria-hidden /></span>
              <div>
                <div className="text-[13px] text-muted">The doctor sees</div>
                <div className="text-2xl font-semibold tracking-tight">85% risk</div>
              </div>
            </div>
            <div className="grid gap-2 text-[13px] sm:grid-cols-2">
              {[
                ["Calibrated probability", "a trustworthy %, not a raw score"],
                ["Decision threshold", "chosen on validation data, not fixed at 50%"],
                ["Risk band", "low · borderline-low · elevated · high"],
                ["What drives it", "Shapley values: which factors raised or lowered the risk"],
                ["Out-of-range warning", "flags inputs unlike any training patient"],
                ["Feedback", "the doctor rates whether it helped"],
              ].map(([a, b]) => (
                <div key={a} className="flex gap-2"><Activity className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden /><span><b>{a}</b>: <span className="text-muted">{b}</span></span></div>
              ))}
            </div>
          </div>
        </Section>

        <Section n={5} title="Who does what" sub="Five roles, each sees only what it needs.">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {[
              { icon: ShieldCheck, t: "Platform admin", d: "Adds hospitals and their admins, promotes models.", no: "No patient access", c: "chart-1" },
              { icon: Building2, t: "Hospital admin", d: "Adds clinicians, uploads training data, approves shares.", no: "Own hospital only", c: "chart-2" },
              { icon: Stethoscope, t: "Clinician", d: "Registers patients, assesses risk, requests records.", no: "Own patients only", c: "chart-3" },
              { icon: FlaskConical, t: "Data scientist", d: "Launches federated training, picks privacy level.", no: "Never sees a patient", c: "chart-4" },
              { icon: ScrollText, t: "Auditor", d: "Verifies and exports the audit log.", no: "Read-only", c: "chart-5" },
            ].map((r) => (
              <div key={r.t} className="rounded-2xl border border-border bg-surface p-4">
                <span className="mb-2 grid size-9 place-items-center rounded-lg text-white" style={{ background: `var(--${r.c})` }}><r.icon className="size-4.5" aria-hidden /></span>
                <div className="text-[14px] font-semibold">{r.t}</div>
                <div className="mt-0.5 text-[12.5px] text-muted">{r.d}</div>
                <div className="mt-2 inline-block rounded-full bg-surface-2 px-2 py-0.5 text-[11.5px] font-medium">{r.no}</div>
              </div>
            ))}
          </div>
        </Section>

        <Section n={6} title="Trust and safety built in">
          <div className="grid gap-4 md:grid-cols-3">
            <Tile icon={Users} title="Consent-based record sharing" tone="chart-2">
              A doctor at another hospital can see a record only with patient consent and admin approval. Revoking consent destroys the key instantly.
            </Tile>
            <Tile icon={Link2} title="Tamper-proof audit log" tone="chart-5">
              Every action is chained by SHA-256 hashes. Editing or deleting any entry breaks the chain and is detected.
            </Tile>
            <Tile icon={Hospital} title="Per-hospital encryption" tone="chart-1">
              Patient records and training data are encrypted at rest with each hospital&apos;s own key.
            </Tile>
          </div>
        </Section>

        <Section n={7} title="Key results" sub="Mainly UCI Heart: 920 patients, 4 real hospitals, repeated cross-validation. AUROC: 1.0 = perfect, 0.5 = guessing.">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat value="0.873" label="Federated LR" sub="vs 0.885 if all data were pooled: nearly as good, with no data shared." />
            <Stat value="0.840" label="DP-SGD at ε = 3" sub="vs 0.629 for the paper's privacy method, and with a real privacy guarantee." tone="success" />
            <Stat value="0.776" label="SCAFFOLD, very different hospitals" sub="vs 0.640 for FedAvg when hospitals' patients differ strongly (Cardio-70k, 4 simulated hospitals, α = 0.1)." tone="chart-2" />
            <Stat value="Same" label="Accuracy with encryption" sub="HE gives identical AUROC to plain FedAvg; the cost is about 500× more upload." tone="chart-4" />
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Stat value="11" label="Problems found in the base paper" sub="e.g. a fixed 50% threshold gave sensitivity 0.000 at 6.4% prevalence." tone="warning" />
            <Stat value="0.69–0.74" label="Sensitivity with a validated threshold" sub="up from 0.000: the model actually catches sick patients." tone="success" />
            <Stat value="140+" label="Automated tests" sub="44 engine + 97 backend tests, plus 8 browser flows." tone="chart-3" />
          </div>
        </Section>

        <motion.div {...fade} className="mt-14 flex flex-col items-center gap-3 rounded-3xl border border-border bg-surface p-8 text-center">
          <Sparkles className="size-6 text-primary" aria-hidden />
          <p className="max-w-2xl text-lg font-semibold tracking-tight">
            Better heart-risk prediction from many hospitals&apos; data, without any hospital giving up its patients&apos; privacy.
          </p>
          <Button className="mt-2" onClick={back}><ArrowLeft /> Back</Button>
        </motion.div>
      </div>
    </main>
  );
}
