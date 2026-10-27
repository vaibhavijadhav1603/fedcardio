"use client";

import { motion } from "framer-motion";
import {
  Activity, Archive, Ban, BrainCircuit, CircleCheck, CircleDashed, Cpu, Gauge, Loader2, Lock, Network, Play, Radio, Server,
  ShieldCheck, Sparkles, TriangleAlert, Users,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { ChartTooltip, useChartTheme } from "@/components/charts";
import {
  Badge, Button, Card, CardBody, CardHeader, EmptyState, ErrorState, Field, Input, LoadingRows, NativeSelect,
  PageHeader, Progress, Slider, Stat, Switch, Tip,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { bytes, cn, num, pct, timeAgo } from "@/lib/utils";

interface Node {
  id: number;
  name: string;
  hospital: string;
  status: string;
  n_records: number;
  cert_fingerprint: string;
  last_seen: string;
}
interface Job {
  id: number;
  name: string;
  config: Record<string, string | number | boolean>;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: number;
  history: { round: number; val_auroc: number; bytes_up: number; elapsed_s: number }[];
  metrics: Record<string, number>;
  epsilon: number | null;
  bytes_up: number;
  error: string;
  created_at: string;
  finished_at: string | null;
  registrable: boolean;
  registered_model: string | null;
}

const ALGOS = [
  { v: "fedavg", l: "FedAvg", d: "Weighted average of client updates (McMahan et al.) — the paper's baseline." },
  { v: "fedprox", l: "FedProx", d: "Adds a proximal term that limits client drift under non-IID data." },
  { v: "scaffold", l: "SCAFFOLD", d: "Control variates correct client drift; doubles communication." },
  { v: "fedadam", l: "FedAdam", d: "Adaptive server optimizer on the aggregated pseudo-gradient." },
  { v: "fedbn", l: "FedBN", d: "Keeps normalization layers local to each hospital." },
];

export default function FederatedPage() {
  const { can } = useAuth();
  const nodes = useApi<Node[]>("/fl/nodes");
  const jobs = useApi<Job[]>("/fl/jobs", { poll: 1500 });
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (selected == null && jobs.data?.length) setSelected(jobs.data[0].id);
  }, [jobs.data, selected]);
  const job = jobs.data?.find((j) => j.id === selected) ?? null;
  const totalRecords = nodes.data?.reduce((a, n) => a + n.n_records, 0) ?? 0;

  return (
    <>
      <PageHeader
        eyebrow={<Badge tone="primary"><Network /> Horizontal cross-silo federation</Badge>}
        title="Federated training console"
        description="Launch training across hospital nodes. Patient records stay on each site; only model updates travel — optionally encrypted (CKKS), masked (SecAgg) or privatised (DP-SGD)."
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Nodes online" value={`${nodes.data?.filter((n) => n.status === "online").length ?? "–"} / ${nodes.data?.length ?? "–"}`} icon={<Server />} />
        <Stat label="Records (never shared)" value={totalRecords.toLocaleString()} icon={<Lock />} tone="success" sub="stay inside each hospital" />
        <Stat label="Jobs run" value={jobs.data?.length ?? "–"} icon={<Activity />} tone="accent" />
        <Stat label="Transport" value="mTLS" icon={<ShieldCheck />} tone="warning" sub="client certificates per node" />
      </div>

      {/* nodes */}
      <Card className="mb-6">
        <CardHeader icon={<Radio />} title="Hospital nodes" description="Each node trains locally on its own data partition." />
        <CardBody>
          {nodes.loading ? <LoadingRows rows={1} /> : nodes.error ? <ErrorState error={nodes.error} onRetry={() => nodes.reload()} /> : !nodes.data!.length ? (
            <EmptyState icon={<Server />} title="No hospital nodes yet" description="A hospital joins training when its admin uploads a dataset under Administration → Training data. At least two are needed." />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {nodes.data!.map((n, i) => {
                const active = job?.status === "running";
                return (
                  <motion.div key={n.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}
                    className={cn("relative overflow-hidden rounded-xl border border-border bg-surface-2 p-4", active && "border-primary/40")}>
                    {active && <motion.div className="absolute inset-x-0 top-0 h-0.5 bg-primary" animate={{ x: ["-100%", "100%"] }} transition={{ duration: 1.6, repeat: Infinity, delay: i * 0.2 }} />}
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2 text-[13px] font-semibold"><Cpu className="size-4 text-primary" /> {n.name}</span>
                      <Badge tone={n.status === "online" ? "success" : n.status === "no data" ? "warning" : "danger"}><span className="size-1.5 rounded-full bg-current" /> {n.status}</Badge>
                    </div>
                    <div className="mt-2 text-[12.5px] text-muted">{n.hospital}</div>
                    <div className="mt-3 flex items-end justify-between">
                      <div><div className="tabular text-xl font-semibold">{n.n_records}</div><div className="text-[11px] text-muted">local records</div></div>
                      <Tip content={`Client certificate ${n.cert_fingerprint}`}><span className="cursor-help font-mono text-[10.5px] text-subtle">{n.cert_fingerprint.slice(0, 18)}…</span></Tip>
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        {can("fl:run") ? <Launcher onLaunched={(id) => { jobs.reload(); setSelected(id); }} /> : (
          <Card className="p-6"><EmptyState icon={<Lock />} title="Read-only access" description="Only data scientists can launch training jobs. You can monitor jobs and their privacy budgets." /></Card>
        )}
        <div className="min-w-0 space-y-6">
          {job ? <JobView job={job} onCancelled={() => jobs.reload()} canRun={can("fl:run")} /> : jobs.loading ? <Card className="p-6"><LoadingRows /></Card> : (
            <Card className="p-8"><EmptyState icon={<Sparkles />} title="No training jobs yet" description="Configure a job on the left and launch it. Progress streams here round by round." /></Card>
          )}
          {!!jobs.data?.length && (
            <Card>
              <CardHeader title="Job history" description="Click a job to inspect it." />
              <CardBody className="pt-3">
                <ul className="divide-y divide-border">
                  {jobs.data.map((j) => (
                    <li key={j.id}>
                      <button onClick={() => setSelected(j.id)} className={cn("flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-left transition-colors hover:bg-surface-2", selected === j.id && "bg-surface-2")}>
                        <StatusIcon s={j.status} />
                        <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium">#{j.id} · {j.name}</span><span className="text-[11.5px] text-muted">{timeAgo(j.created_at)}</span></span>
                        {j.metrics?.auroc != null && <span className="tabular text-[13px] font-semibold">AUROC {num(j.metrics.auroc)}</span>}
                      </button>
                    </li>
                  ))}
                </ul>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function StatusIcon({ s }: { s: Job["status"] }) {
  if (s === "running") return <Loader2 className="size-4 animate-spin text-primary" aria-label="running" />;
  if (s === "completed") return <CircleCheck className="size-4 text-success" aria-label="completed" />;
  if (s === "failed") return <TriangleAlert className="size-4 text-danger" aria-label="failed" />;
  if (s === "cancelled") return <Ban className="size-4 text-subtle" aria-label="cancelled" />;
  return <CircleDashed className="size-4 text-subtle" aria-label="queued" />;
}

function Launcher({ onLaunched }: { onLaunched: (id: number) => void }) {
  const [algorithm, setAlgorithm] = useState("fedavg");
  const [model, setModel] = useState("paper_nn");
  const [rounds, setRounds] = useState(30);
  const [epochs, setEpochs] = useState(5);
  const [dp, setDp] = useState(false);
  const [he, setHe] = useState(false);
  const [secagg, setSecagg] = useState(false);
  const [eps, setEps] = useState(3);
  const [classWeight, setClassWeight] = useState(false);
  const [dropout, setDropout] = useState(0);
  const [busy, setBusy] = useState(false);

  const privacy = dp ? (he ? "dpsgd+he" : secagg ? "dpsgd+secagg" : "dpsgd") : he ? "he" : secagg ? "secagg" : "none";
  const invalid = algorithm === "scaffold" && dp ? "SCAFFOLD's control variates are not privatised, so it cannot be combined with DP-SGD." : null;

  async function launch() {
    setBusy(true);
    try {
      const j = await api<Job>("/fl/jobs", { method: "POST", json: { algorithm, model, rounds, local_epochs: epochs, privacy, dp_epsilon: eps, class_weight: classWeight, dropout_prob: dropout } });
      toast.success("Training launched", { description: j.name });
      onLaunched(j.id);
    } catch (e) {
      toast.error("Could not launch", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="h-fit">
      <CardHeader icon={<Play />} title="Launch a training job" description="Runs on the 4 UCI hospital partitions." />
      <CardBody className="space-y-5">
        <Field label="Algorithm" htmlFor="algo" hint={ALGOS.find((a) => a.v === algorithm)?.d}>
          <NativeSelect id="algo" value={algorithm} onChange={(e) => setAlgorithm(e.target.value)}>
            {ALGOS.map((a) => <option key={a.v} value={a.v}>{a.l}</option>)}
          </NativeSelect>
        </Field>
        <Field label="Model" htmlFor="model">
          <NativeSelect id="model" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="paper_nn">Paper NN (d→5→LayerNorm→1)</option>
            <option value="lr">Logistic regression</option>
            <option value="mlp">MLP 16×2</option>
          </NativeSelect>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Rounds" htmlFor="rounds"><Input id="rounds" type="number" min={1} max={300} value={rounds} onChange={(e) => setRounds(Number(e.target.value))} /></Field>
          <Field label="Local epochs" htmlFor="epochs"><Input id="epochs" type="number" min={1} max={50} value={epochs} onChange={(e) => setEpochs(Number(e.target.value))} disabled={dp} /></Field>
        </div>
        <div className="space-y-4 rounded-xl border border-border p-4">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-subtle">Privacy mechanisms</div>
          <Switch id="dp" checked={dp} onCheckedChange={setDp} label="Differential privacy (DP-SGD)" description="Record-level, RDP-accounted over all rounds" />
          {dp && (
            <div className="space-y-2 pl-1">
              <div className="flex justify-between text-[12.5px]"><span className="text-muted">Privacy budget ε (δ = 10⁻⁵)</span><span className="tabular font-semibold">{eps.toFixed(1)}</span></div>
              <Slider label="Privacy budget epsilon" value={eps} min={0.5} max={10} step={0.5} onValueChange={setEps} />
              <div className="flex justify-between text-[11px] text-subtle"><span>stronger privacy</span><span>higher utility</span></div>
            </div>
          )}
          <Switch id="he" checked={he} onCheckedChange={(v) => { setHe(v); if (v) setSecagg(false); }} label="Homomorphic encryption (CKKS)" description="Server aggregates ciphertexts only" />
          <Switch id="sa" checked={secagg} onCheckedChange={(v) => { setSecagg(v); if (v) setHe(false); }} label="Secure aggregation (masking)" description="Lightweight alternative to HE" />
        </div>
        <Switch id="cw" checked={classWeight} onCheckedChange={setClassWeight} label="Class-weighted loss" description="Counter class imbalance per site" />
        <div className="space-y-2">
          <div className="flex justify-between text-[12.5px]"><span className="text-muted">Client dropout per round</span><span className="tabular font-semibold">{pct(dropout)}</span></div>
          <Slider label="Client dropout probability" value={dropout} min={0} max={0.6} step={0.1} onValueChange={setDropout} />
        </div>
        {invalid && <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{invalid}</p>}
        <Button className="w-full" size="lg" onClick={launch} loading={busy} disabled={!!invalid}><Play /> Launch training</Button>
      </CardBody>
    </Card>
  );
}

function JobView({ job, onCancelled, canRun }: { job: Job; onCancelled: () => void; canRun: boolean }) {
  const t = useChartTheme();
  const data = useMemo(() => job.history.map((h) => ({ round: h.round, auroc: h.val_auroc, mb: h.bytes_up / 1e6 })), [job.history]);
  const target = Number(job.config.dp_epsilon);
  const usesDp = String(job.config.privacy).includes("dpsgd");
  const last = job.history.at(-1);
  const [registering, setRegistering] = useState(false);
  async function cancel() {
    try {
      await api(`/fl/jobs/${job.id}/cancel`, { method: "POST" });
      toast("Cancellation requested");
      onCancelled();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }
  async function register() {
    setRegistering(true);
    try {
      await api(`/fl/jobs/${job.id}/register`, { method: "POST" });
      toast.success("Model registered for review", { description: "It is in the Model registry as staging. The platform admin decides whether to promote it." });
      onCancelled(); // reload the job list
    } catch (e) {
      toast.error("Could not register", { description: (e as Error).message });
    } finally {
      setRegistering(false);
    }
  }
  const registerAction = job.registered_model ? (
    <Link href="/models"><Badge tone="accent"><BrainCircuit /> In registry · staging</Badge></Link>
  ) : canRun && job.registrable ? (
    <Button size="sm" onClick={register} loading={registering}><Archive /> Register model</Button>
  ) : null;
  return (
    <Card>
      <CardHeader
        icon={<Gauge />}
        title={<span className="flex items-center gap-2">Job #{job.id} <Badge tone={job.status === "completed" ? "success" : job.status === "failed" ? "danger" : job.status === "running" ? "primary" : "neutral"}><StatusIcon s={job.status} /> {job.status}</Badge></span>}
        description={job.name}
        action={canRun && (job.status === "running" || job.status === "queued") ? <Button size="sm" variant="secondary" onClick={cancel}><Ban /> Cancel</Button> : registerAction}
      />
      <CardBody className="space-y-5">
        <div>
          <div className="mb-1.5 flex justify-between text-[12.5px]"><span className="text-muted">Round {last?.round ?? 0} of {String(job.config.rounds)}</span><span className="tabular font-medium">{pct(job.progress)}</span></div>
          <Progress value={job.progress * 100} label="Training progress" />
        </div>
        <div className="grid gap-3 sm:grid-cols-4">
          <MiniStat label="Validation AUROC" value={num(last?.val_auroc ?? job.metrics.auroc)} />
          <MiniStat label="Test AUROC" value={num(job.metrics.auroc)} />
          <MiniStat label="Uploaded" value={bytes(job.bytes_up)} />
          <MiniStat label="Wall time" value={last ? `${last.elapsed_s.toFixed(1)} s` : "—"} />
        </div>
        <div className="h-64" role="img" aria-label="Validation AUROC by round">
          {data.length ? (
            <ResponsiveContainer>
              <LineChart data={data} margin={{ left: -12, right: 8, top: 8 }}>
                <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="round" tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} tickFormatter={(v) => v.toFixed(2)} />
                <Tooltip content={<ChartTooltip labelFmt={(l) => `Round ${l}`} />} />
                <Line type="monotone" dataKey="auroc" name="Validation AUROC" stroke="var(--chart-1)" strokeWidth={2.5} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="grid h-full place-items-center rounded-xl bg-surface-2 text-[13px] text-muted"><span className="flex items-center gap-2"><Loader2 className="size-4 animate-spin" /> Waiting for the first round…</span></div>
          )}
        </div>
        {usesDp && (
          <div className="rounded-xl border border-border p-4">
            <div className="flex items-center justify-between text-[13px]"><span className="font-medium">Privacy budget</span><span className="tabular text-muted">ε = {job.epsilon != null ? job.epsilon.toFixed(2) : `≤ ${target}`} of {target} · δ = 1e-5</span></div>
            <Progress className="mt-2" value={(job.status === "completed" && job.epsilon != null ? job.epsilon / target : job.progress) * 100} tone={job.progress > 0.85 ? "warning" : "primary"} label="Privacy budget spent" />
            <p className="mt-2 text-[11.5px] text-muted">Noise is calibrated up-front so the full run spends exactly the target budget (RDP accountant); the bar shows the share spent so far.</p>
          </div>
        )}
        {job.status === "completed" && (
          <div className="grid gap-3 sm:grid-cols-4">
            {([["sensitivity", "Sensitivity"], ["specificity", "Specificity"], ["auprc", "AUPRC"], ["brier", "Brier score"]] as const).map(([k, l]) => <MiniStat key={k} label={l} value={num(job.metrics[k])} />)}
            {Object.entries(job.metrics).filter(([k]) => k.startsWith("auroc_")).map(([k, v]) => <MiniStat key={k} label={`AUROC · ${k.slice(6).replace(/_/g, " ")}`} value={num(v)} />)}
            {job.metrics.he_encrypt_s != null && <MiniStat label="HE encrypt time" value={`${job.metrics.he_encrypt_s.toFixed(2)} s`} />}
          </div>
        )}
        {job.status === "failed" && <pre className="max-h-40 overflow-auto rounded-xl bg-danger-soft p-3 text-[11.5px] text-danger">{job.error}</pre>}
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(job.config).map(([k, v]) => <Badge key={k}><span className="text-subtle">{k}</span> {String(v)}</Badge>)}
        </div>
        <p className="flex items-center gap-1.5 text-[11.5px] text-muted"><Users className="size-3.5" /> Validation and test sets stay local; the pooled scores shown stand in for a federated evaluation over per-site score histograms.</p>
      </CardBody>
    </Card>
  );
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-surface-2 px-3 py-2.5">
      <div className="truncate text-[11.5px] text-muted">{label}</div>
      <div className="tabular mt-0.5 text-[16px] font-semibold">{value}</div>
    </div>
  );
}
