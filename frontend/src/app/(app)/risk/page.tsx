"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  Activity, AlertTriangle, CalendarClock, Copy, FileHeart, IdCard, Info, Printer, Search, ShieldCheck, ThumbsDown, ThumbsUp, UserRound,
  Wand2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { BAND, ContributionBars, explain, RiskGauge, type Prediction } from "@/components/risk";
import {
  Badge, Button, Card, CardBody, CardHeader, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows,
  NativeSelect, PageHeader, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Textarea,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { cn, fmtDate, pct } from "@/lib/utils";

interface PatientRow {
  id: number;
  pseudo_id: string;
  display_name: string;
  sex: string;
  age: number;
  birth_year: number;
  hospital_name: string;
}
interface PatientFull extends PatientRow {
  features: Record<string, number>;
  fhir: unknown;
}
interface SchemaField {
  key: string;
  label: string;
  kind: "number" | "select";
  unit?: string;
  min?: number;
  max?: number;
  options?: { value: number; label: string }[];
}
interface ConsentRow {
  id: number;
  purpose: string;
  granted_to: string;
  valid_until: string;
  revoked_at: string | null;
  active: boolean;
  created_at: string;
}

export default function RiskPage() {
  const { m } = useI18n();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);
  const list = useApi<PatientRow[]>(`/patients?limit=100&q=${encodeURIComponent(debounced)}`);
  const schema = useApi<{ fields: SchemaField[] }>("/predict/schema");
  const [selected, setSelected] = useState<number | null>(null);
  const [mode, setMode] = useState<"patient" | "manual">("patient");
  const patient = useApi<PatientFull>(selected && mode === "patient" ? `/patients/${selected}` : null);
  const [pred, setPred] = useState<Prediction | null>(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState<Record<string, string>>({ age: "58", sex: "1", cp: "4", trestbps: "140", chol: "260", fbs: "0", restecg: "0", thalach: "130", exang: "1", oldpeak: "1.8" });

  useEffect(() => setPred(null), [selected, mode]);

  async function assess() {
    setBusy(true);
    try {
      const body =
        mode === "patient"
          ? { patient_id: selected }
          : { features: Object.fromEntries(Object.entries(manual).map(([k, v]) => [k, v === "" ? null : Number(v)])) };
      setPred(await api<Prediction>("/predict", { method: "POST", json: body }));
    } catch (e) {
      toast.error("Assessment failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow={<Badge tone="primary"><Activity /> Clinical decision support · research</Badge>}
        title={m.risk.title}
        description={m.risk.subtitle}
      />
      <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        {/* patient list */}
        <Card className="flex max-h-[calc(100dvh-220px)] min-h-[420px] flex-col overflow-hidden">
          <div className="border-b border-border p-4">
            <div role="group" aria-label="Input mode" className="flex h-10 w-full items-center gap-1 rounded-xl border border-border bg-surface-2 p-1">
              {([["patient", <UserRound key="i" />, "Patients"], ["manual", <Wand2 key="i" />, m.risk.manual]] as const).map(([v, icon, label]) => (
                <button key={v} type="button" aria-pressed={mode === v} onClick={() => setMode(v)}
                  className={cn("inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-lg text-[13px] font-medium text-muted transition-all hover:text-fg [&_svg]:size-3.5",
                    mode === v && "bg-surface text-fg shadow-sm")}>
                  {icon} {label}
                </button>
              ))}
            </div>
            {mode === "patient" && (
              <div className="relative mt-3">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
                <Input
                  aria-label={m.risk.searchPatients}
                  placeholder={m.risk.searchPatients}
                  className="pl-9"
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                />
              </div>
            )}
          </div>
          {mode === "patient" ? (
            <div className="scrollbar-thin flex-1 overflow-y-auto p-2" role="listbox" aria-label="Patients">
              {list.loading && !list.data ? (
                <div className="p-2"><LoadingRows rows={6} /></div>
              ) : list.error ? (
                <ErrorState error={list.error} onRetry={() => list.reload()} />
              ) : !list.data?.length ? (
                <EmptyState icon={<Search />} title="No matching patients" description="Try a different name or pseudonym." />
              ) : (
                list.data.map((p) => (
                  <button
                    key={p.id}
                    role="option"
                    aria-selected={selected === p.id}
                    onClick={() => setSelected(p.id)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                      selected === p.id ? "bg-primary-soft" : "hover:bg-surface-2",
                    )}
                  >
                    <span className={cn("grid size-9 shrink-0 place-items-center rounded-full text-[12px] font-semibold", selected === p.id ? "bg-primary text-primary-fg" : "bg-surface-3 text-muted")}>
                      {p.display_name.split(" ").map((s) => s[0]).join("")}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-medium">{p.display_name}</span>
                      <span className="block truncate font-mono text-[11px] text-muted">{p.pseudo_id}</span>
                    </span>
                    <span className="text-right text-[11.5px] text-muted">
                      {p.age} y<br />{p.sex === "male" ? "M" : "F"}
                    </span>
                  </button>
                ))
              )}
            </div>
          ) : (
            <form className="scrollbar-thin flex-1 space-y-3 overflow-y-auto p-4" onSubmit={(e) => { e.preventDefault(); assess(); }}>
              {schema.loading ? <LoadingRows rows={6} /> : schema.data?.fields.map((f) => (
                <Field key={f.key} label={<>{f.label}{f.unit && <span className="font-normal text-muted"> ({f.unit})</span>}</>} htmlFor={`f-${f.key}`}>
                  {f.kind === "select" ? (
                    <NativeSelect id={`f-${f.key}`} value={manual[f.key] ?? ""} onChange={(e) => setManual({ ...manual, [f.key]: e.target.value })}>
                      <option value="">Not recorded</option>
                      {f.options!.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </NativeSelect>
                  ) : (
                    <Input id={`f-${f.key}`} type="number" inputMode="decimal" step="any" min={f.min} max={f.max} placeholder="Not recorded"
                      value={manual[f.key] ?? ""} onChange={(e) => setManual({ ...manual, [f.key]: e.target.value })} />
                  )}
                </Field>
              ))}
              <Button type="submit" className="w-full" loading={busy}><Activity /> {m.risk.assess}</Button>
            </form>
          )}
        </Card>

        {/* detail */}
        <div className="min-w-0 space-y-6">
          {mode === "patient" && !selected ? (
            <Card className="p-8">
              <EmptyState icon={<FileHeart />} title="Select a patient" description="Choose a patient from your hospital to review their record and estimate risk. Every access is written to the audit log." />
            </Card>
          ) : mode === "patient" ? (
            <PatientCard patient={patient.data} loading={patient.loading} error={patient.error} onRetry={() => patient.reload()} onAssess={assess} busy={busy} />
          ) : null}

          <AnimatePresence mode="wait">
            {busy && !pred && (
              <motion.div key="sk" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <Card className="grid gap-6 p-6 md:grid-cols-2"><Skeleton className="h-48" /><Skeleton className="h-48" /></Card>
              </motion.div>
            )}
            {pred && <ResultCard key={pred.model_id + pred.probability} pred={pred} />}
          </AnimatePresence>
        </div>
      </div>
    </>
  );
}

function PatientCard({ patient, loading, error, onRetry, onAssess, busy }: {
  patient: PatientFull | null;
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  onAssess: () => void;
  busy: boolean;
}) {
  const [idOpen, setIdOpen] = useState(false);
  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (loading || !patient) return <Card className="p-6"><LoadingRows rows={3} /></Card>;
  const f = patient.features;
  const items: [string, string][] = [
    ["Resting BP", f.trestbps != null ? `${f.trestbps} mmHg` : "—"],
    ["Cholesterol", f.chol != null ? `${f.chol} mg/dL` : "—"],
    ["Max heart rate", f.thalach != null ? `${f.thalach} bpm` : "—"],
    ["ST depression", f.oldpeak != null ? `${f.oldpeak} mm` : "—"],
    ["Chest pain", ({ 1: "Typical", 2: "Atypical", 3: "Non-anginal", 4: "Asymptomatic" } as Record<number, string>)[f.cp] ?? "—"],
    ["Exercise angina", f.exang == null ? "—" : f.exang ? "Yes" : "No"],
    ["Fasting sugar >120", f.fbs == null ? "—" : f.fbs ? "Yes" : "No"],
    ["Resting ECG", ({ 0: "Normal", 1: "ST-T abnormality", 2: "LVH" } as Record<number, string>)[f.restecg] ?? "—"],
  ];
  return (
    <Card>
      <CardHeader
        icon={<UserRound />}
        title={patient.display_name}
        description={<span className="font-mono">{patient.pseudo_id} · {patient.age} years · {patient.sex}</span>}
        action={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setIdOpen(true)}><IdCard /> ID card</Button>
            <Button onClick={onAssess} loading={busy}><Activity /> Assess risk</Button>
          </div>
        }
      />
      <IdCardDialog patient={patient} open={idOpen} onOpenChange={setIdOpen} />
      <CardBody>
        <Tabs defaultValue="record">
          <TabsList>
            <TabsTrigger value="record">Record</TabsTrigger>
            <TabsTrigger value="consent"><ShieldCheck /> Consent</TabsTrigger>
            <TabsTrigger value="fhir">FHIR</TabsTrigger>
          </TabsList>
          <TabsContent value="record">
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {items.map(([k, v]) => (
                <div key={k} className="rounded-xl bg-surface-2 px-3 py-2.5">
                  <dt className="text-[11.5px] text-muted">{k}</dt>
                  <dd className={cn("tabular mt-0.5 text-[14px] font-medium", v === "—" && "text-subtle")}>{v}</dd>
                </div>
              ))}
            </dl>
          </TabsContent>
          <TabsContent value="consent"><ConsentPanel patientId={patient.id} /></TabsContent>
          <TabsContent value="fhir">
            <pre className="scrollbar-thin max-h-80 overflow-auto rounded-xl bg-surface-2 p-4 font-mono text-[11.5px] leading-relaxed text-muted">
              {JSON.stringify(patient.fhir, null, 2)}
            </pre>
          </TabsContent>
        </Tabs>
      </CardBody>
    </Card>
  );
}

function IdCardDialog({ patient, open, onOpenChange }: { patient: PatientFull; open: boolean; onOpenChange: (o: boolean) => void }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(patient.pseudo_id);
      toast.success("Patient ID copied");
    } catch {
      toast.error("Could not copy", { description: "Select the ID and copy it manually." });
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Patient ID card"
      description="Give this ID to the patient (printed card or referral letter). Another hospital needs it, or the patient's exact details, to request this record."
      footer={<><Button variant="secondary" onClick={() => window.print()}><Printer /> Print</Button><Button onClick={copy}><Copy /> Copy ID</Button></>}>
      <div className="rounded-2xl bg-gradient-to-br from-primary to-accent p-5 text-white shadow-lg">
        <div className="flex items-center justify-between text-[11.5px] font-medium uppercase tracking-wider opacity-90">
          <span>FedCardio health ID</span>
          <IdCard className="size-4" aria-hidden />
        </div>
        <div data-testid="id-name" className="mt-4 text-[18px] font-semibold">{patient.display_name}</div>
        <div className="mt-1 select-all font-mono text-[20px] tracking-wide">{patient.pseudo_id}</div>
        <div className="mt-4 grid grid-cols-3 gap-2 text-[12px]">
          <div><div className="opacity-80">Born</div><div className="font-medium">{patient.birth_year}</div></div>
          <div><div className="opacity-80">Sex</div><div className="font-medium capitalize">{patient.sex}</div></div>
          <div><div className="opacity-80">Registered at</div><div className="font-medium">{patient.hospital_name}</div></div>
        </div>
      </div>
    </Dialog>
  );
}

function ConsentPanel({ patientId }: { patientId: number }) {
  const consents = useApi<ConsentRow[]>(`/patients/${patientId}/consents`);
  const hospitals = useApi<{ id: number; name: string }[]>("/hospitals");
  const [open, setOpen] = useState(false);
  const [purpose, setPurpose] = useState("treatment");
  const [to, setTo] = useState("");
  const [days, setDays] = useState("180");
  const [busy, setBusy] = useState(false);

  async function record() {
    setBusy(true);
    try {
      await api(`/patients/${patientId}/consents`, { method: "POST", json: { purpose, granted_to_hospital_id: to ? Number(to) : null, valid_days: Number(days) } });
      toast.success("Consent recorded");
      setOpen(false);
      consents.reload();
    } catch (e) {
      toast.error("Could not record consent", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: number) {
    try {
      await api(`/consents/${id}/revoke`, { method: "POST" });
      toast.success("Consent revoked", { description: "Any shares relying on it were revoked and their keys destroyed." });
      consents.reload();
    } catch (e) {
      toast.error("Could not revoke", { description: (e as Error).message });
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-muted">Patient consent controls whether other hospitals may receive this record.</p>
        <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>Record consent</Button>
      </div>
      {consents.loading ? <LoadingRows rows={2} /> : consents.error ? <ErrorState error={consents.error} onRetry={() => consents.reload()} /> :
        !consents.data?.length ? <EmptyState icon={<ShieldCheck />} title="No consent on file" description="Sharing requests for this patient cannot be approved until consent is recorded." /> : (
          <ul className="divide-y divide-border rounded-xl border border-border">
            {consents.data.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <Badge tone={c.active ? "success" : "neutral"}>{c.active ? "Active" : c.revoked_at ? "Revoked" : "Expired"}</Badge>
                <span className="text-[13px] font-medium capitalize">{c.purpose.replace("_", " ")}</span>
                <span className="text-[12.5px] text-muted">→ {c.granted_to}</span>
                <span className="ml-auto flex items-center gap-1 text-[12px] text-muted"><CalendarClock className="size-3.5" /> until {fmtDate(c.valid_until)}</span>
                {c.active && <Button size="sm" variant="ghost" className="text-danger" onClick={() => revoke(c.id)}>Revoke</Button>}
              </li>
            ))}
          </ul>
        )}
      <Dialog open={open} onOpenChange={setOpen} title="Record patient consent" description="Document the patient's informed consent for sharing their record."
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={record} loading={busy}>Record consent</Button></>}>
        <div className="grid gap-4">
          <Field label="Purpose" htmlFor="c-purpose">
            <NativeSelect id="c-purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
              <option value="treatment">Treatment</option>
              <option value="care_coordination">Care coordination</option>
              <option value="research">Research</option>
            </NativeSelect>
          </Field>
          <Field label="Recipient" htmlFor="c-to" hint="Leave as 'Any' to allow any participating hospital.">
            <NativeSelect id="c-to" value={to} onChange={(e) => setTo(e.target.value)}>
              <option value="">Any participating hospital</option>
              {hospitals.data?.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Valid for (days)" htmlFor="c-days">
            <Input id="c-days" type="number" min={1} max={3650} value={days} onChange={(e) => setDays(e.target.value)} />
          </Field>
        </div>
      </Dialog>
    </div>
  );
}

function ResultCard({ pred }: { pred: Prediction }) {
  const { m } = useI18n();
  const band = BAND[pred.risk_band];
  const sentences = useMemo(() => explain(pred), [pred]);
  const [fbOpen, setFbOpen] = useState(false);
  const [comment, setComment] = useState("");
  async function sendFeedback(helpful: boolean, text = "") {
    try {
      await api("/feedback", { method: "POST", json: { model_id: pred.model_id, helpful, comment: text } });
      toast.success("Thanks — feedback recorded");
      setFbOpen(false);
    } catch (e) {
      toast.error("Could not send feedback", { description: (e as Error).message });
    }
  }
  return (
    <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.35 }}>
      <Card className="overflow-hidden">
        <div className="grid gap-0 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="border-b border-border p-6 lg:border-b-0 lg:border-r">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Risk estimate</h2>
              <Badge tone={band.tone}>{band.label} risk</Badge>
            </div>
            <div className="mt-6"><RiskGauge p={pred.probability} threshold={pred.threshold} band={pred.risk_band} /></div>
            <div className="mt-6 grid grid-cols-3 gap-2 text-center">
              {[["Threshold", pct(pred.threshold)], ["Uncalibrated", pct(pred.probability_uncalibrated)], ["Population avg", pct(pred.baseline_probability)]].map(([k, v]) => (
                <div key={k} className="rounded-xl bg-surface-2 py-2"><div className="tabular text-[15px] font-semibold">{v}</div><div className="text-[11px] text-muted">{k}</div></div>
              ))}
            </div>
            <div className="mt-4 space-y-2">
              {pred.ood_warning && (
                <div role="alert" className="flex gap-2 rounded-xl bg-danger-soft p-3 text-[12.5px] text-danger">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" /> Out-of-distribution input ({pred.ood_features.join(", ")}). The model has not seen values like these; treat the estimate as unreliable.
                </div>
              )}
              {pred.missing_inputs.length > 0 && (
                <div className="flex gap-2 rounded-xl bg-warning-soft p-3 text-[12.5px] text-warning">
                  <Info className="mt-0.5 size-4 shrink-0" /> Missing: {pred.missing_inputs.join(", ")} — imputed from training averages.
                </div>
              )}
            </div>
          </div>
          <div className="p-6">
            <h2 className="text-[15px] font-semibold">{m.risk.drivers}</h2>
            <p className="mt-0.5 text-[12.5px] text-muted">Shapley contributions (log-odds). <span className="text-danger">Red</span> raises the estimate, <span className="text-primary">teal</span> lowers it.</p>
            <div className="mt-5"><ContributionBars items={pred.contributions} /></div>
            <div className="mt-6 space-y-2 rounded-xl bg-surface-2 p-4 text-[13px] leading-relaxed">
              {sentences.map((s, i) => <p key={i}>{s}</p>)}
            </div>
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <span className="text-[11.5px] text-muted">Model <span className="font-mono">{pred.model_id}</span> · v{pred.model_version}</span>
              <div className="flex items-center gap-1">
                <span className="mr-1 text-[12.5px] text-muted">{m.risk.feedback}</span>
                <Button size="icon" variant="ghost" aria-label="Helpful" onClick={() => sendFeedback(true)}><ThumbsUp /></Button>
                <Button size="icon" variant="ghost" aria-label="Not helpful" onClick={() => setFbOpen(true)}><ThumbsDown /></Button>
              </div>
            </div>
          </div>
        </div>
        <div className="border-t border-warning/20 bg-warning-soft px-6 py-2.5 text-[12px] text-warning">{pred.disclaimer}</div>
      </Card>
      <Dialog open={fbOpen} onOpenChange={setFbOpen} title="What was wrong?" description="Your feedback is logged with the model version to help evaluate the prototype."
        footer={<><Button variant="secondary" onClick={() => setFbOpen(false)}>Cancel</Button><Button onClick={() => sendFeedback(false, comment)}>Send feedback</Button></>}>
        <Field label="Comment" htmlFor="fb"><Textarea id="fb" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. explanation did not match clinical picture" /></Field>
      </Dialog>
    </motion.div>
  );
}
