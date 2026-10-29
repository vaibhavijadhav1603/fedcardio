"use client";

import { motion } from "framer-motion";
import {
  ArrowDownLeft, ArrowUpRight, Ban, Check, Clock, Eye, FileLock2, IdCard, KeyRound, Lock, Plus, Search, Share2, ShieldCheck, UserSearch, X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Badge, Button, Card, CardBody, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, NativeSelect,
  PageHeader, Stat, Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Textarea, Th,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { fmtDate, timeAgo } from "@/lib/utils";

interface Share {
  id: number;
  pseudo_id: string;
  purpose: string;
  justification: string;
  status: "pending" | "approved" | "denied" | "revoked" | "expired";
  owner_hospital: string;
  owner_hospital_id: number;
  requesting_hospital: string;
  requesting_hospital_id: number;
  requested_by: string;
  decided_by: string | null;
  created_at: string;
  decided_at: string | null;
  expires_at: string | null;
  consent_on_file: boolean;
}

const STATUS = {
  pending: { tone: "warning", icon: Clock, label: "Pending" },
  approved: { tone: "success", icon: Check, label: "Approved" },
  denied: { tone: "danger", icon: X, label: "Denied" },
  revoked: { tone: "neutral", icon: Ban, label: "Revoked" },
  expired: { tone: "neutral", icon: Clock, label: "Expired" },
} as const;

export default function SharingPage() {
  const { user, can } = useAuth();
  const shares = useApi<Share[]>("/shares?direction=all");
  const [tab, setTab] = useState(can("share:decide") && !can("share:request") ? "incoming" : "outgoing");
  const [reqOpen, setReqOpen] = useState(false);
  const [decide, setDecide] = useState<Share | null>(null);
  const [view, setView] = useState<Share | null>(null);

  const incoming = useMemo(() => shares.data?.filter((s) => s.owner_hospital_id === user?.hospital_id) ?? [], [shares.data, user]);
  const outgoing = useMemo(() => shares.data?.filter((s) => s.requesting_hospital_id === user?.hospital_id) ?? [], [shares.data, user]);
  const pending = incoming.filter((s) => s.status === "pending").length;

  async function revoke(s: Share) {
    try {
      await api(`/shares/${s.id}/revoke`, { method: "POST" });
      toast.success("Access revoked", { description: "The recipient's decryption key was destroyed." });
      shares.reload();
    } catch (e) {
      toast.error("Could not revoke", { description: (e as Error).message });
    }
  }

  return (
    <>
      <PageHeader
        eyebrow={<Badge tone="accent"><Share2 /> Consent-based exchange · FHIR R4</Badge>}
        title="Patient record sharing"
        description="Request records from other hospitals, approve requests for your patients, and keep a complete history. Records are envelope-encrypted and only released under an active patient consent."
        actions={can("share:request") && <Button onClick={() => setReqOpen(true)}><Plus /> New request</Button>}
      />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Awaiting your decision" value={pending} icon={<Clock />} tone="warning" sub="incoming requests" />
        <Stat label="Active shares out" value={incoming.filter((s) => s.status === "approved").length} icon={<ArrowUpRight />} tone="primary" sub="your patients, other hospitals" />
        <Stat label="Records you can view" value={outgoing.filter((s) => s.status === "approved").length} icon={<Eye />} tone="accent" sub="approved, not expired" />
        <Stat label="Encryption" value="AES-256-GCM" icon={<Lock />} tone="success" sub="per-record key, per-hospital KEK" />
      </div>

      <Card>
        <CardBody>
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList>
              <TabsTrigger value="outgoing"><ArrowDownLeft /> My requests <Badge className="ml-1">{outgoing.length}</Badge></TabsTrigger>
              <TabsTrigger value="incoming"><ArrowUpRight /> Requests for our patients {pending > 0 && <Badge tone="warning" className="ml-1">{pending}</Badge>}</TabsTrigger>
            </TabsList>
            {shares.loading && !shares.data ? <div className="mt-5"><LoadingRows /></div> : shares.error ? <div className="mt-5"><ErrorState error={shares.error} onRetry={() => shares.reload()} /></div> : (
              <>
                <TabsContent value="outgoing">
                  <ShareTable rows={outgoing} perspective="requester" onView={setView}
                    empty={<EmptyState icon={<Share2 />} title="No requests yet" description="Request a record from another hospital using the patient's pseudonymous ID."
                      action={can("share:request") && <Button size="sm" onClick={() => setReqOpen(true)}><Plus /> New request</Button>} />} />
                </TabsContent>
                <TabsContent value="incoming">
                  <ShareTable rows={incoming} perspective="owner" onDecide={can("share:decide") ? setDecide : undefined} onRevoke={can("share:decide") ? revoke : undefined}
                    empty={<EmptyState icon={<ShieldCheck />} title="No incoming requests" description="When another hospital requests one of your patients' records it will appear here." />} />
                </TabsContent>
              </>
            )}
          </Tabs>
        </CardBody>
      </Card>

      <RequestDialog open={reqOpen} onOpenChange={setReqOpen} onDone={() => { shares.reload(); setTab("outgoing"); }} />
      <DecideDialog share={decide} onClose={() => setDecide(null)} onDone={() => shares.reload()} />
      <ViewDialog share={view} onClose={() => setView(null)} />
    </>
  );
}

function ShareTable({ rows, perspective, onDecide, onRevoke, onView, empty }: {
  rows: Share[];
  perspective: "owner" | "requester";
  onDecide?: (s: Share) => void;
  onRevoke?: (s: Share) => void;
  onView?: (s: Share) => void;
  empty: React.ReactNode;
}) {
  if (!rows.length) return <>{empty}</>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Patient</Th>
          <Th>{perspective === "owner" ? "Requested by" : "Held by"}</Th>
          <Th>Purpose</Th>
          <Th>Status</Th>
          <Th>Timeline</Th>
          <Th className="text-right">Actions</Th>
        </tr>
      </thead>
      <tbody>
        {rows.map((s, i) => {
          const st = STATUS[s.status];
          return (
            <motion.tr key={s.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.02 }} className="hover:bg-surface-2/50">
              <Td><span className="font-mono text-[12.5px]">{s.pseudo_id}</span></Td>
              <Td>
                <div className="text-[13px] font-medium">{perspective === "owner" ? s.requesting_hospital : s.owner_hospital}</div>
                <div className="text-[11.5px] text-muted">{s.requested_by}</div>
              </Td>
              <Td>
                <div className="text-[13px] capitalize">{s.purpose.replace("_", " ")}</div>
                <div className="max-w-xs truncate text-[11.5px] text-muted" title={s.justification}>{s.justification}</div>
              </Td>
              <Td>
                <Badge tone={st.tone}><st.icon /> {st.label}</Badge>
                {perspective === "owner" && s.status === "pending" && (
                  <div className="mt-1 text-[11px]">{s.consent_on_file ? <span className="text-success">consent on file</span> : <span className="text-warning">no matching consent</span>}</div>
                )}
              </Td>
              <Td className="text-[12px] text-muted">
                <div>Requested {timeAgo(s.created_at)}</div>
                {s.decided_at && <div>Decided {timeAgo(s.decided_at)}{s.decided_by && ` by ${s.decided_by}`}</div>}
                {s.expires_at && s.status === "approved" && <div className="text-fg">Expires {fmtDate(s.expires_at)}</div>}
              </Td>
              <Td className="text-right">
                <div className="flex justify-end gap-1.5">
                  {onDecide && s.status === "pending" && <Button size="sm" onClick={() => onDecide(s)}>Review</Button>}
                  {onRevoke && s.status === "approved" && <Button size="sm" variant="secondary" className="text-danger" onClick={() => onRevoke(s)}><Ban /> Revoke</Button>}
                  {onView && s.status === "approved" && <Button size="sm" variant="soft" onClick={() => onView(s)}><FileLock2 /> Open record</Button>}
                </div>
              </Td>
            </motion.tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function RequestDialog({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const [mode, setMode] = useState<"details" | "id">("details");
  const [name, setName] = useState("");
  const [birthYear, setBirthYear] = useState("");
  const [sex, setSex] = useState("female");
  const [pseudo, setPseudo] = useState("");
  const [found, setFound] = useState<{ pseudo_id: string; hospital_name: string } | null>(null);
  const [lookupErr, setLookupErr] = useState<string | null>(null);
  const [purpose, setPurpose] = useState("treatment");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);

  async function lookup() {
    setLookupErr(null);
    setFound(null);
    try {
      if (mode === "id") {
        setFound(await api(`/patients/directory?pseudo_id=${encodeURIComponent(pseudo.trim())}`));
      } else {
        const qs = new URLSearchParams({ name: name.trim(), birth_year: birthYear, sex });
        const hit = await api<{ pseudo_id: string; hospital_name: string }>(`/patients/match?${qs}`);
        setPseudo(hit.pseudo_id);
        setFound(hit);
      }
    } catch (e) {
      setLookupErr((e as Error).message);
    }
  }
  async function submit() {
    setBusy(true);
    try {
      await api("/shares", { method: "POST", json: { pseudo_id: pseudo.trim(), purpose, justification: why } });
      toast.success("Request sent", { description: `The record owner at ${found?.hospital_name} will review it.` });
      onOpenChange(false);
      setPseudo(""); setName(""); setBirthYear(""); setFound(null); setWhy("");
      onDone();
    } catch (e) {
      toast.error("Request failed", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Request a patient record" description="Find the patient by their details or their ID. Requests and every search are audited."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy} disabled={!found || why.trim().length < 5}>Send request</Button></>}>
      <div className="grid gap-4">
        <Tabs value={mode} onValueChange={(v) => { setMode(v as "details" | "id"); setFound(null); setLookupErr(null); }}>
          <TabsList>
            <TabsTrigger value="details"><UserSearch /> Patient details</TabsTrigger>
            <TabsTrigger value="id"><IdCard /> I have the ID</TabsTrigger>
          </TabsList>
        </Tabs>
        {mode === "details" ? (
          <div className="grid gap-3">
            <Field label="Full name" htmlFor="mname" hint="Exact name as registered at the other hospital">
              <Input id="mname" value={name} onChange={(e) => { setName(e.target.value); setFound(null); }} placeholder="e.g. Arjun Weber" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Birth year" htmlFor="myear">
                <Input id="myear" inputMode="numeric" value={birthYear} onChange={(e) => { setBirthYear(e.target.value.replace(/\D/g, "").slice(0, 4)); setFound(null); }} placeholder="e.g. 1968" />
              </Field>
              <Field label="Sex" htmlFor="msex">
                <NativeSelect id="msex" value={sex} onChange={(e) => { setSex(e.target.value); setFound(null); }}>
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                </NativeSelect>
              </Field>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="secondary" onClick={lookup} disabled={name.trim().length < 3 || birthYear.length !== 4}><Search /> Find patient</Button>
              <span className="text-[12px] text-muted">All three must match exactly one patient. Every search is audited.</span>
            </div>
            {lookupErr && <p role="alert" className="text-[12.5px] text-danger">{lookupErr}</p>}
          </div>
        ) : (
          <Field label="Patient ID" htmlFor="pseudo" error={lookupErr} hint="From the patient's ID card or a referral letter. Format PX-XXXXXXXXXXXXXXXX">
            <div className="flex gap-2">
              <Input id="pseudo" value={pseudo} onChange={(e) => { setPseudo(e.target.value.toUpperCase()); setFound(null); }} placeholder="PX-…" className="font-mono" />
              <Button variant="secondary" onClick={lookup} disabled={pseudo.trim().length < 6}><Search /> Find</Button>
            </div>
          </Field>
        )}
        {found && (
          <div className="flex items-center gap-2 rounded-xl bg-success-soft px-3 py-2 text-[13px] text-success">
            <Check className="size-4" /> Record held by <strong>{found.hospital_name}</strong>
            <span className="ml-auto font-mono text-[12px]">{found.pseudo_id}</span>
          </div>
        )}
        <Field label="Purpose" htmlFor="purpose" hint="Purpose limitation: the record can only be used for this purpose.">
          <NativeSelect id="purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)}>
            <option value="treatment">Treatment</option>
            <option value="care_coordination">Care coordination</option>
            <option value="research">Research</option>
          </NativeSelect>
        </Field>
        <Field label="Clinical justification" htmlFor="why" error={why && why.trim().length < 5 ? "At least 5 characters" : null}>
          <Textarea id="why" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. Patient transferred to our cardiology unit for angiography" />
        </Field>
      </div>
    </Dialog>
  );
}

function DecideDialog({ share, onClose, onDone }: { share: Share | null; onClose: () => void; onDone: () => void }) {
  const [days, setDays] = useState("30");
  const [busy, setBusy] = useState<"approve" | "deny" | null>(null);
  async function decide(approve: boolean) {
    if (!share) return;
    setBusy(approve ? "approve" : "deny");
    try {
      await api(`/shares/${share.id}/decide`, { method: "POST", json: { approve, valid_days: Number(days) } });
      toast.success(approve ? "Access granted" : "Request denied", { description: approve ? "The record key was re-wrapped for the requesting hospital." : undefined });
      onClose();
      onDone();
    } catch (e) {
      toast.error("Decision failed", { description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }
  return (
    <Dialog open={!!share} onOpenChange={(o) => !o && onClose()} title="Review sharing request"
      footer={<><Button variant="secondary" onClick={() => decide(false)} loading={busy === "deny"}><X /> Deny</Button><Button onClick={() => decide(true)} loading={busy === "approve"} disabled={!share?.consent_on_file}><Check /> Approve</Button></>}>
      {share && (
        <div className="space-y-4 text-[13px]">
          <dl className="grid grid-cols-2 gap-3">
            {[["Patient", <span key="p" className="font-mono">{share.pseudo_id}</span>], ["Requesting hospital", share.requesting_hospital], ["Requested by", share.requested_by], ["Purpose", <span key="pu" className="capitalize">{share.purpose.replace("_", " ")}</span>]].map(([k, v]) => (
              <div key={k as string} className="rounded-xl bg-surface-2 px-3 py-2"><dt className="text-[11.5px] text-muted">{k}</dt><dd className="mt-0.5 font-medium">{v}</dd></div>
            ))}
          </dl>
          <div className="rounded-xl border border-border p-3"><div className="text-[11.5px] text-muted">Justification</div><p className="mt-1">{share.justification}</p></div>
          {share.consent_on_file ? (
            <div className="flex gap-2 rounded-xl bg-success-soft p-3 text-success"><ShieldCheck className="size-4 shrink-0" /> An active patient consent covers this purpose and recipient.</div>
          ) : (
            <div className="flex gap-2 rounded-xl bg-warning-soft p-3 text-warning"><KeyRound className="size-4 shrink-0" /> No matching consent. Record the patient&apos;s consent (Risk assessment → patient → Consent) before approving.</div>
          )}
          <Field label="Access valid for (days)" htmlFor="days" hint="Access also ends automatically if the patient's consent expires or is revoked.">
            <Input id="days" type="number" min={1} max={365} value={days} onChange={(e) => setDays(e.target.value)} />
          </Field>
        </div>
      )}
    </Dialog>
  );
}

function ViewDialog({ share, onClose }: { share: Share | null; onClose: () => void }) {
  const rec = useApi<{ fhir: { entry: { resource: { resourceType: string; code?: { text: string }; valueQuantity?: { value: number; unit: string }; gender?: string; birthDate?: string } }[] } }>(
    share ? `/shares/${share.id}/record` : null,
  );
  return (
    <Dialog wide open={!!share} onOpenChange={(o) => !o && onClose()} title={<span className="flex items-center gap-2"><FileLock2 className="size-5 text-primary" /> Shared record</span>}
      description={share ? `${share.pseudo_id} · from ${share.owner_hospital} · purpose: ${share.purpose.replace("_", " ")}` : undefined}>
      {rec.loading ? <LoadingRows rows={4} /> : rec.error ? <ErrorState error={rec.error} /> : rec.data && (
        <div className="space-y-4">
          <div className="grid gap-2 sm:grid-cols-2">
            {rec.data.fhir.entry.map((e, i) => {
              const r = e.resource;
              if (r.resourceType === "Patient") return (
                <div key={i} className="rounded-xl bg-primary-soft px-3 py-2.5 sm:col-span-2"><div className="text-[11.5px] text-primary">Patient</div><div className="font-medium capitalize">{r.gender} · born {r.birthDate}</div></div>
              );
              return (
                <div key={i} className="rounded-xl bg-surface-2 px-3 py-2.5">
                  <div className="text-[11.5px] text-muted">{r.code?.text}</div>
                  <div className="tabular font-medium">{r.valueQuantity?.value} <span className="text-muted">{r.valueQuantity?.unit?.replace(/[{}]/g, "")}</span></div>
                </div>
              );
            })}
          </div>
          <p className="text-[12px] text-muted">Decrypted for your hospital only. This view was recorded in the audit log.</p>
        </div>
      )}
    </Dialog>
  );
}
