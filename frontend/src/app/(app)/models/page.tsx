"use client";

import { BrainCircuit, CheckCircle2, FileText, History, Rocket, ShieldCheck, Undo2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  Badge, Button, Card, CardBody, CardHeader, Dialog, EmptyState, ErrorState, LoadingRows, PageHeader,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { fmtDate, num, pct } from "@/lib/utils";

interface ModelCard {
  id: string;
  version: string;
  name: string;
  training_method: string;
  architecture: string;
  dataset: string;
  target: string;
  intended_use: string;
  limitations: string[];
  validation_metrics: Record<string, number>;
  threshold: { rule: string; value: number };
  calibration: { method: string };
  shap_site_consistency_spearman_mean: number;
  privacy: { mechanism: string };
  git_commit: string;
  features: { names: string[] };
}
interface ModelVersion {
  id: string;
  version: string;
  name: string;
  stage: "production" | "staging" | "archived";
  sha256: string;
  created_at: string;
  promoted_at: string | null;
  card: ModelCard;
}

export default function ModelsPage() {
  const { can } = useAuth();
  const models = useApi<ModelVersion[]>("/models");
  const [confirm, setConfirm] = useState<{ m: ModelVersion; action: "promote" | "rollback" } | null>(null);
  const [busy, setBusy] = useState(false);

  async function act() {
    if (!confirm) return;
    setBusy(true);
    try {
      await api(`/models/${confirm.m.id}/${confirm.action}`, { method: "POST" });
      toast.success(confirm.action === "promote" ? "Model promoted to production" : "Rolled back to previous version");
      setConfirm(null);
      models.reload();
    } catch (e) {
      toast.error("Action failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader eyebrow={<Badge tone="primary"><BrainCircuit /> Versioned · hashed · audited</Badge>} title="Model registry"
        description="Every served model has a model card describing intended use, data, metrics, fairness and limitations. Promotion and rollback are restricted to platform admins and audited." />
      {models.loading ? <LoadingRows /> : models.error ? <ErrorState error={models.error} onRetry={() => models.reload()} /> : !models.data?.length ? (
        <EmptyState icon={<BrainCircuit />} title="No models registered" description="Export a model with `python -m experiments.run_explain`." />
      ) : (
        <div className="space-y-6">
          {models.data.map((m) => (
            <Card key={m.id} className="overflow-hidden">
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-border p-5">
                <div className="flex items-start gap-3">
                  <div className="grid size-11 place-items-center rounded-xl bg-gradient-to-br from-primary to-accent text-white"><BrainCircuit className="size-5" /></div>
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-[16px] font-semibold">{m.name}</h2>
                      <Badge tone={m.stage === "production" ? "success" : m.stage === "staging" ? "warning" : "neutral"}>
                        {m.stage === "production" && <CheckCircle2 />} {m.stage}
                      </Badge>
                      <Badge>v{m.version}</Badge>
                    </div>
                    <div className="mt-1 font-mono text-[11.5px] text-muted">{m.id} · sha256 {m.sha256.slice(0, 16)}… · commit {m.card.git_commit?.slice(0, 7)}</div>
                  </div>
                </div>
                {can("model:promote") && (
                  <div className="flex gap-2">
                    {m.stage !== "production" && <Button size="sm" onClick={() => setConfirm({ m, action: "promote" })}><Rocket /> Promote</Button>}
                    {m.stage === "production" && <Button size="sm" variant="secondary" onClick={() => setConfirm({ m, action: "rollback" })}><Undo2 /> Roll back</Button>}
                  </div>
                )}
              </div>
              <div className="grid gap-0 lg:grid-cols-3">
                <section className="space-y-4 border-b border-border p-5 lg:border-b-0 lg:border-r">
                  <H icon={<FileText />}>Intended use</H>
                  <p className="text-[13px] leading-relaxed">{m.card.intended_use}</p>
                  <dl className="space-y-2 text-[12.5px]">
                    <Row k="Target" v={m.card.target} />
                    <Row k="Data" v={m.card.dataset} />
                    <Row k="Training" v={m.card.training_method} />
                    <Row k="Architecture" v={m.card.architecture.replace("_", " ")} />
                    <Row k="Privacy" v={m.card.privacy.mechanism} />
                    <Row k="Features" v={`${m.card.features.names.length} inputs`} />
                  </dl>
                </section>
                <section className="space-y-4 border-b border-border p-5 lg:border-b-0 lg:border-r">
                  <H icon={<CheckCircle2 />}>Validation metrics</H>
                  <div className="grid grid-cols-2 gap-2">
                    {[["AUROC", num(m.card.validation_metrics.auroc)], ["AUPRC", num(m.card.validation_metrics.auprc)], ["Brier", num(m.card.validation_metrics.brier)], ["ECE", num(m.card.validation_metrics.ece)],
                      ["Sensitivity", pct(m.card.validation_metrics.sensitivity)], ["Specificity", pct(m.card.validation_metrics.specificity)]].map(([k, v]) => (
                      <div key={k} className="rounded-xl bg-surface-2 px-3 py-2"><div className="text-[11px] text-muted">{k}</div><div className="tabular text-[15px] font-semibold">{v}</div></div>
                    ))}
                  </div>
                  <dl className="space-y-2 text-[12.5px]">
                    <Row k="Threshold" v={`${pct(m.card.threshold.value, 1)} (${m.card.threshold.rule.replaceAll("_", " ")})`} />
                    <Row k="Calibration" v={m.card.calibration.method} />
                    <Row k="SHAP site consistency" v={`ρ = ${num(m.card.shap_site_consistency_spearman_mean, 2)}`} />
                  </dl>
                </section>
                <section className="space-y-3 p-5">
                  <H icon={<ShieldCheck />}>Limitations</H>
                  <ul className="space-y-2">
                    {m.card.limitations.map((l) => <li key={l} className="flex gap-2 text-[13px] leading-relaxed"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-warning" />{l}</li>)}
                    <li className="flex gap-2 text-[13px] leading-relaxed"><span className="mt-2 size-1.5 shrink-0 rounded-full bg-warning" />Single threshold gives lower sensitivity for women (see Experiments → Sites & fairness).</li>
                  </ul>
                  <div className="flex items-center gap-1.5 pt-2 text-[12px] text-muted"><History className="size-3.5" /> Created {fmtDate(m.created_at)}{m.promoted_at && ` · promoted ${fmtDate(m.promoted_at)}`}</div>
                </section>
              </div>
            </Card>
          ))}
        </div>
      )}
      <Dialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)}
        title={confirm?.action === "promote" ? "Promote to production?" : "Roll back production model?"}
        description={confirm?.action === "promote" ? "All new predictions will use this model. The current production model will be archived." : "The most recently archived production model will be restored."}
        footer={<><Button variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button><Button onClick={act} loading={busy}>{confirm?.action === "promote" ? "Promote" : "Roll back"}</Button></>} />
    </>
  );
}

function H({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return <h3 className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-subtle [&_svg]:size-3.5">{icon}{children}</h3>;
}
function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex gap-3"><dt className="w-28 shrink-0 text-muted">{k}</dt><dd className="min-w-0 flex-1">{v}</dd></div>;
}
