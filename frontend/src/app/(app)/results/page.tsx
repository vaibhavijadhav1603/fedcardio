"use client";

import {
  ArrowDownToLine, ArrowRight, BarChart3, FlaskConical, Lock, Scale, ShieldAlert, Shuffle, TrendingUp,
} from "lucide-react";
import { useMemo } from "react";
import {
  Bar, BarChart, CartesianGrid, ErrorBar, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { toast } from "sonner";
import { ChartTooltip, SERIES, useChartTheme } from "@/components/charts";
import {
  Button, Card, CardBody, CardHeader, EmptyState, ErrorState, LoadingRows, PageHeader, Table,
  Tabs, TabsContent, TabsList, TabsTrigger, Td, Th,
} from "@/components/ui";
import { download } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { bytes, cn, num, pct } from "@/lib/utils";

type Row = Record<string, number | string | boolean | null> & { method?: string; k: number };
interface Summary {
  available: string[];
  uci?: Row[];
  uci_policies?: Row[];
  uci_sites?: Row[];
  uci_history?: { method: string; round: number; val_auroc: number }[];
  noniid?: Row[];
  clients?: Row[];
  privacy?: Row[];
  imbalance?: Row[];
  attacks?: { attack: string; mechanism: string; relative_error: number | null; attack_auc: number | null }[];
  fairness?: Row[];
  paper_table2: { method: string; learner: string; auroc: number; sensitivity: number; specificity: number }[];
  p1_uci?: Row[];
}

const n = (v: unknown) => (typeof v === "number" ? v : null);

export default function ResultsPage() {
  const s = useApi<Summary>("/results/summary");
  return (
    <>
      <PageHeader
        title="Experiments & evidence"
      />
      {s.loading ? <LoadingRows rows={6} /> : s.error ? <ErrorState error={s.error} onRetry={() => s.reload()} /> : !s.data?.uci ? (
        <EmptyState icon={<FlaskConical />} title="No results yet" description="Run `make reproduce` to generate experiment results." />
      ) : (
        <Tabs defaultValue="overview">
          <div className="scrollbar-thin -mx-1 overflow-x-auto px-1 pb-1">
            <TabsList>
              <TabsTrigger value="overview"><TrendingUp /> Overview</TabsTrigger>
              <TabsTrigger value="privacy"><Lock /> Privacy–utility</TabsTrigger>
              <TabsTrigger value="noniid"><Shuffle /> Non-IID & scale</TabsTrigger>
              <TabsTrigger value="sites"><Scale /> Sites & fairness</TabsTrigger>
              <TabsTrigger value="attacks"><ShieldAlert /> Attacks</TabsTrigger>
              <TabsTrigger value="paper"><BarChart3 /> vs. base paper</TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="overview"><Overview s={s.data} /></TabsContent>
          <TabsContent value="privacy"><Privacy s={s.data} /></TabsContent>
          <TabsContent value="noniid"><NonIID s={s.data} /></TabsContent>
          <TabsContent value="sites"><Sites s={s.data} /></TabsContent>
          <TabsContent value="attacks"><Attacks s={s.data} /></TabsContent>
          <TabsContent value="paper"><Paper s={s.data} /></TabsContent>
        </Tabs>
      )}
    </>
  );
}

const find = (rows: Row[] | undefined, m: string) => rows?.find((r) => r.method === m);

function Delta({ a, b, label, sub }: { a?: Row; b?: Row; label: string; sub: string }) {
  if (!a || !b) return null;
  const d = (n(a.auroc) ?? 0) - (n(b.auroc) ?? 0);
  return (
    <Card className="p-5">
      <div className="text-[12.5px] font-medium text-muted">{label}</div>
      <div className="mt-3 flex items-center gap-3">
        <div><div className="tabular text-2xl font-semibold">{num(n(a.auroc))}</div><div className="max-w-[9rem] truncate text-[11px] text-muted" title={a.method}>{a.method}</div></div>
        <ArrowRight className="size-4 text-subtle" />
        <div><div className="tabular text-2xl font-semibold text-muted">{num(n(b.auroc))}</div><div className="max-w-[9rem] truncate text-[11px] text-muted" title={b.method}>{b.method}</div></div>
      </div>
      <div className={cn("tabular mt-3 inline-flex rounded-full px-2 py-0.5 text-[12px] font-semibold", d > 0.005 ? "bg-success-soft text-success" : d < -0.005 ? "bg-danger-soft text-danger" : "bg-surface-2 text-muted")}>
        ΔAUROC {d >= 0 ? "+" : ""}{d.toFixed(3)}
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-muted">{sub}</p>
    </Card>
  );
}

function Overview({ s }: { s: Summary }) {
  const u = s.uci!;
  const bestOurs = [...u].filter((r) => !r.paper_reimpl).sort((a, b) => (n(b.auroc) ?? 0) - (n(a.auroc) ?? 0))[0];
  const bestPaper = [...u].filter((r) => r.paper_reimpl).sort((a, b) => (n(b.auroc) ?? 0) - (n(a.auroc) ?? 0))[0];
  const plainNN = find(u, "FedAvg-NN (paper)");
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Delta a={find(u, "DP-SGD-NN eps=3")} b={find(u, "FedAvg_DP-SVT-NN (paper)")} label="Accounted DP vs paper's SVT-DP (NN)" sub="DP-SGD carries a formal (ε=3, δ=1e-5) record-level guarantee over all rounds; the paper's SVT filter has none." />
        <Delta a={find(u, "DP-SGD-LR eps=3")} b={find(u, "FedAvg_DP-SVT-LR (paper)")} label="Accounted DP vs paper's SVT-DP (LR)" sub="Same comparison for logistic regression." />
        <Delta a={find(u, "SCAFFOLD-NN")} b={plainNN} label="Drift-aware FL vs FedAvg (paper NN)" sub="SCAFFOLD's control variates counter client drift across the 4 very different hospitals." />
        <Delta a={bestOurs} b={bestPaper} label="Best overall: ours vs paper re-impl." sub="Best AUROC among our methods vs the best paper re-implementation (including centralised)." />
      </div>
      {s.uci_history && <Convergence h={s.uci_history} />}
    </div>
  );
}

function Convergence({ h }: { h: NonNullable<Summary["uci_history"]> }) {
  const t = useChartTheme();
  const methods = ["SCAFFOLD-NN", "FedProx-NN mu=0.01", "FedAvg_DP-SVT-NN (paper)", "DP-SGD-NN eps=3"];
  const data = useMemo(() => {
    const by: Record<number, Record<string, number>> = {};
    h.filter((r) => methods.includes(r.method)).forEach((r) => ((by[r.round] ??= { round: r.round })[r.method] = r.val_auroc));
    return Object.values(by).sort((a, b) => a.round - b.round);
  }, [h]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card>
      <CardHeader icon={<TrendingUp />} title="Convergence (UCI, fold 1)" description="Global-model validation AUROC by communication round." />
      <CardBody className="h-80">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ left: -10, right: 12 }}>
            <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="round" tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} />
            <YAxis domain={[0.4, 1]} tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} />
            <Tooltip content={<ChartTooltip labelFmt={(l) => `Round ${l}`} />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {methods.map((m, i) => <Line key={m} dataKey={m} stroke={SERIES[i + 1]} strokeWidth={2} dot={false} isAnimationActive={false} strokeDasharray={m.includes("SVT") ? "4 3" : undefined} />)}
          </LineChart>
        </ResponsiveContainer>
      </CardBody>
    </Card>
  );
}

function Privacy({ s }: { s: Summary }) {
  const t = useChartTheme();
  const pv = s.privacy ?? [];
  const curve = pv.filter((r) => String(r.method).startsWith("DP-SGD eps=") && !String(r.method).endsWith("inf"))
    .map((r) => ({ eps: Number(String(r.method).split("=")[1]), auroc: n(r.auroc), err: [(n(r.auroc) ?? 0) - (n(r.auroc_lo) ?? n(r.auroc) ?? 0), (n(r.auroc_hi) ?? n(r.auroc) ?? 0) - (n(r.auroc) ?? 0)] }))
    .sort((a, b) => a.eps - b.eps);
  const noDp = find(pv, "FedAvg (no DP)");
  const svt = find(pv, "FedAvg_DP-SVT (paper)");
  const uciCurve = (s.uci ?? []).filter((r) => String(r.method).startsWith("DP-SGD-LR eps=")).map((r) => ({ eps: Number(String(r.method).split("=")[1]), auroc: n(r.auroc) })).sort((a, b) => a.eps - b.eps);
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader icon={<Lock />} title="Privacy–utility curve · Cardio-70k" description="Record-level DP-SGD (paper NN), 4 Dirichlet(α=0.5) clients, δ=1e-5, 3 seeds." />
        <CardBody className="h-80">
          {curve.length ? (
            <ResponsiveContainer>
              <LineChart data={curve} margin={{ left: -10, right: 16 }}>
                <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="eps" type="number" scale="log" domain={["dataMin", "dataMax"]} ticks={curve.map((c) => c.eps)} tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} label={{ value: "ε (log scale)", position: "insideBottom", offset: -2, fill: t.axis, fontSize: 11 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} tickFormatter={(v: number) => v.toFixed(2)} />
                <Tooltip content={<ChartTooltip labelFmt={(l) => `ε = ${l}`} />} />
                {noDp && <ReferenceLine y={n(noDp.auroc)!} stroke="var(--chart-2)" strokeDasharray="5 4" label={{ value: "FedAvg, no DP", fill: t.axis, fontSize: 11, position: "insideTopRight" }} />}
                {svt && <ReferenceLine y={n(svt.auroc)!} stroke="var(--chart-4)" strokeDasharray="5 4" label={{ value: "Paper SVT-DP (no ε guarantee)", fill: t.axis, fontSize: 11, position: "insideBottomRight" }} />}
                <Line dataKey="auroc" name="DP-SGD AUROC" stroke="var(--chart-1)" strokeWidth={2.5} dot={{ r: 4 }} isAnimationActive={false}>
                  <ErrorBar dataKey="err" width={4} stroke="var(--chart-1)" />
                </Line>
              </LineChart>
            </ResponsiveContainer>
          ) : <EmptyState title="Privacy sweep not run yet" description="python -m experiments.run_federated --suite privacy" />}
        </CardBody>
      </Card>
      <Card>
        <CardHeader icon={<Lock />} title="Cost of each privacy mechanism · Cardio-70k" description="Upload volume over the run (log scale) and AUROC." />
        <CardBody>
          {pv.length ? (
            <Table>
              <thead><tr><Th>Mechanism</Th><Th>AUROC</Th><Th>Upload</Th><Th>Guarantee</Th></tr></thead>
              <tbody>
                {pv.filter((r) => !String(r.method).startsWith("DP-SGD eps=") || ["DP-SGD eps=1", "DP-SGD eps=8"].includes(String(r.method))).map((r) => (
                  <tr key={r.method as string}>
                    <Td className="text-[13px] font-medium">{r.method}</Td>
                    <Td className="tabular">{num(n(r.auroc))}</Td>
                    <Td className="tabular text-[12.5px]">{bytes(n(r.bytes_up))}</Td>
                    <Td className="text-[12px] text-muted">{String(r.method).includes("HE") ? "server sees ciphertext" : String(r.method).includes("SecAgg") ? "server sees only the sum" : String(r.method).includes("SVT") ? "none formal" : String(r.method).includes("DP-SGD") ? `(ε, δ) record-level` : "—"}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : <EmptyState title="Not available" />}
          {uciCurve.length > 0 && <p className="mt-4 text-[12.5px] text-muted">UCI (LR): AUROC {uciCurve.map((c) => `${num(c.auroc)} at ε=${c.eps}`).join(" · ")}.</p>}
        </CardBody>
      </Card>
    </div>
  );
}

function NonIID({ s }: { s: Summary }) {
  const t = useChartTheme();
  const rows = s.noniid ?? [];
  const algos = [...new Set(rows.map((r) => r.method as string))];
  const alphas = ["0.1", "0.5", "1.0", "inf"];
  const data = alphas.map((a) => ({ alpha: a === "inf" ? "∞ (IID)" : a, ...Object.fromEntries(rows.filter((r) => r.alpha === a).map((r) => [r.method, n(r.worst_site_auroc)])) }));
  const pooled = alphas.map((a) => ({ alpha: a === "inf" ? "∞ (IID)" : a, ...Object.fromEntries(rows.filter((r) => r.alpha === a).map((r) => [r.method, n(r.auroc)])) }));
  const clients = (s.clients ?? []).map((r) => ({ name: `${r.n_clients} clients${n(r.dropout) ? `, ${pct(n(r.dropout))} dropout` : ""}`, auroc: n(r.auroc) }));
  if (!rows.length) return <EmptyState title="Non-IID sweep not run yet" description="python -m experiments.run_federated --suite noniid" />;
  const chart = (d: typeof data, title: string, desc: string) => (
    <Card>
      <CardHeader icon={<Shuffle />} title={title} description={desc} />
      <CardBody className="h-80">
        <ResponsiveContainer>
          <LineChart data={d} margin={{ left: -10, right: 12 }}>
            <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="alpha" tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} label={{ value: "Dirichlet α (smaller = more skew)", position: "insideBottom", offset: -2, fill: t.axis, fontSize: 11 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} tickFormatter={(v: number) => v.toFixed(2)} />
            <Tooltip content={<ChartTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {algos.map((a, i) => <Line key={a} dataKey={a} stroke={SERIES[i % SERIES.length]} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />)}
          </LineChart>
        </ResponsiveContainer>
      </CardBody>
    </Card>
  );
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      {chart(pooled, "Pooled AUROC vs label skew · Cardio-70k", "4 simulated hospitals, 3 seeds.")}
      {chart(data, "Worst-site AUROC vs label skew", "The hospital that the global model serves worst.")}
      {clients.length > 0 && (
        <Card className="xl:col-span-2">
          <CardHeader icon={<BarChart3 />} title="Number of clients & dropout (FedAvg, α=0.5)" description="Robustness to more, smaller sites and to clients failing to report each round." />
          <CardBody className="h-72">
            <ResponsiveContainer>
              <BarChart data={clients} margin={{ left: -10 }}>
                <CartesianGrid stroke={t.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: t.axis, fontSize: 11 }} stroke={t.grid} tickFormatter={(v: number) => v.toFixed(2)} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "var(--surface-2)" }} />
                <Bar dataKey="auroc" name="AUROC" fill="var(--chart-2)" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function Sites({ s }: { s: Summary }) {
  const sites = s.uci_sites ?? [];
  const methods = ["cML-LR (paper)", "FedAvg-LR (paper)", "FedProx-LR mu=0.01", "Local-only NN", "FedAvg-NN (paper)", "SCAFFOLD-NN", "FedBN-NN", "FedAvg-NN + fine-tune"];
  const siteNames = [...new Set(sites.map((r) => r.site as string))];
  const cell = (v: number | null) => {
    if (v == null) return <span className="text-subtle">—</span>;
    const h = Math.max(0, Math.min(1, (v - 0.5) / 0.45));
    return <span className="tabular inline-block w-14 rounded-md py-1 text-center text-[12.5px] font-medium" style={{ background: `color-mix(in oklab, var(--primary) ${Math.round(h * 45)}%, transparent)` }}>{num(v)}</span>;
  };
  const fair = s.fairness ?? [];
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader icon={<Scale />} title="Per-hospital AUROC" description="How well each method serves each hospital (UCI). Darker = better." />
        <CardBody>
          <Table>
            <thead><tr><Th>Method</Th>{siteNames.map((s) => <Th key={s} className="capitalize">{s.replace("_", " ")}</Th>)}</tr></thead>
            <tbody>
              {methods.map((m) => (
                <tr key={m}>
                  <Td className="text-[12.5px] font-medium">{m}</Td>
                  {siteNames.map((st) => <Td key={st}>{cell(n(sites.find((r) => r.method === m && r.site === st)?.auroc))}</Td>)}
                </tr>
              ))}
            </tbody>
          </Table>
          <p className="mt-3 text-[12px] text-muted">Switzerland: 115 of 123 patients are positive, so its AUROC rests on very few negatives.</p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader icon={<Scale />} title="Subgroup performance · deployed model" description="Out-of-fold, FedAvg-LR, one threshold for everyone (Youden on validation)." />
        <CardBody>
          {fair.length ? (
            <Table>
              <thead><tr><Th>Group</Th><Th>n</Th><Th>Prevalence</Th><Th>AUROC</Th><Th>Sens</Th><Th>Spec</Th></tr></thead>
              <tbody>
                {fair.map((r, i) => (
                  <tr key={i}>
                    <Td><span className="text-[11px] uppercase tracking-wide text-subtle">{r.attribute}</span> <span className="font-medium capitalize">{String(r.group).replace("_", " ")}</span></Td>
                    <Td className="tabular">{r.n}</Td>
                    <Td className="tabular">{pct(n(r.prevalence))}</Td>
                    <Td className="tabular">{num(n(r.auroc))}</Td>
                    <Td className="tabular">{num(n(r.sensitivity), 2)}</Td>
                    <Td className="tabular">{num(n(r.specificity), 2)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : <EmptyState title="Fairness analysis not run" />}
          <p className="mt-3 text-[12px] text-muted">A single threshold yields lower sensitivity for women and lower specificity for older patients and VA Long Beach — largely driven by prevalence differences. Recorded in the model card.</p>
        </CardBody>
      </Card>
    </div>
  );
}

function Attacks({ s }: { s: Summary }) {
  const a = s.attacks ?? [];
  const inv = a.filter((r) => r.attack.startsWith("gradient"));
  const mia = a.filter((r) => r.attack.startsWith("membership"));
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card>
        <CardHeader icon={<ShieldAlert />} title="Gradient inversion (server's view)" description="Can a curious server reconstruct a patient from one client's update? Relative reconstruction error (0 = exact recovery)." />
        <CardBody className="space-y-3">
          {inv.map((r) => {
            const e = r.relative_error ?? 0;
            return (
              <div key={r.mechanism}>
                <div className="flex justify-between text-[13px]"><span>{r.mechanism}</span><span className={cn("tabular font-semibold", e < 0.05 ? "text-danger" : "text-success")}>{e.toFixed(3)}</span></div>
                <div className="mt-1 h-2 rounded-full bg-surface-3"><div className={cn("h-2 rounded-full", e < 0.05 ? "bg-danger" : "bg-success")} style={{ width: `${Math.min(100, Math.max(2, (Math.log10(e + 1e-3) + 3) / 4.3 * 100))}%` }} /></div>
              </div>
            );
          })}
          <p className="pt-2 text-[12px] text-muted">Plain FedAvg leaks the exact record for single-sample updates. HE/SecAgg hide individual updates from the server; local noise degrades reconstruction.</p>
        </CardBody>
      </Card>
      <Card>
        <CardHeader icon={<ShieldAlert />} title="Membership inference (released model)" description="Loss-threshold attack AUC; 0.5 means the attacker learns nothing." />
        <CardBody>
          <Table>
            <thead><tr><Th>Mechanism</Th><Th>Attack AUC</Th></tr></thead>
            <tbody>{mia.map((r) => <tr key={r.mechanism}><Td className="text-[13px]">{r.mechanism}</Td><Td className="tabular font-medium">{num(r.attack_auc)}</Td></tr>)}</tbody>
          </Table>
          <p className="mt-3 text-[12px] text-muted">HE and SecAgg release the same model as plain FedAvg, so they cannot reduce this leakage — only DP can. Here DP-SGD at ε=∞ already lowered it, so the residual effect of the noise itself is within seed variation.</p>
        </CardBody>
      </Card>
    </div>
  );
}

function Paper({ s }: { s: Summary }) {
  const u = s.uci ?? [];
  const pairs: [string, string, string][] = [
    ["cML", "NN", "cML-NN (paper)"], ["cML", "LR", "cML-LR (paper)"], ["FedAvg", "NN", "FedAvg-NN (paper)"], ["FedAvg", "LR", "FedAvg-LR (paper)"],
    ["FedAvg_DP", "NN", "FedAvg_DP-SVT-NN (paper)"], ["FedAvg_DP", "LR", "FedAvg_DP-SVT-LR (paper)"], ["FedAvg_HE", "NN", "FedAvg_HE-NN (paper)"], ["FedAvg_HE", "LR", "FedAvg_HE-LR (paper)"],
  ];
  return (
    <Card>
      <CardHeader icon={<BarChart3 />} title="Side by side with Sharma et al. (2026), Table 2"
        description="Paper: Swedish registry, 4-year incident MI/HF, 660k patients, 6.4% prevalence. Ours: same methods re-implemented on public UCI Heart (prevalent CAD, n=920)." />
      <CardBody>
        <Table>
          <thead><tr><Th>Method</Th><Th>Learner</Th><Th>Paper AUC</Th><Th>Paper sens / spec</Th><Th>Ours AUC</Th><Th>Ours sens / spec (honest threshold)</Th></tr></thead>
          <tbody>
            {pairs.map(([m, l, ours]) => {
              const p = s.paper_table2.find((r) => r.method === m && r.learner === l)!;
              const o = find(u, ours);
              return (
                <tr key={ours}>
                  <Td className="font-medium">{m}</Td><Td>{l}</Td>
                  <Td className="tabular">{num(p.auroc)}</Td><Td className="tabular">{num(p.sensitivity, 2)} / {num(p.specificity, 2)}</Td>
                  <Td className="tabular font-semibold">{num(n(o?.auroc))}</Td><Td className="tabular">{num(n(o?.sensitivity), 2)} / {num(n(o?.specificity), 2)}</Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
        <Downloads files={s.available} />
      </CardBody>
    </Card>
  );
}

function Downloads({ files }: { files: string[] }) {
  return (
    <div className="mt-6">
      <div className="mb-2 text-[13px] font-semibold">Raw result files</div>
      <div className="flex flex-wrap gap-2">
        {files.map((f) => (
          <Button key={f} size="sm" variant="secondary" onClick={() => download(`/results/files/${f}`, f).catch((e) => toast.error(e.message))}>
            <ArrowDownToLine /> {f}
          </Button>
        ))}
      </div>
    </div>
  );
}
