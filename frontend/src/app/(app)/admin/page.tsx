"use client";

import {
  Building2, Database, Download, MoreHorizontal, Plus, Power, RotateCcw, ShieldCheck, Trash2, Upload, UserPlus, Users,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import {
  Badge, Button, Card, CardBody, CardHeader, Dialog, EmptyState, ErrorState, Field, Input, LoadingRows, NativeSelect, PageHeader,
  Table, Tabs, TabsContent, TabsList, TabsTrigger, Td, Th,
} from "@/components/ui";
import { api } from "@/lib/api";
import { ROLE_LABEL, useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { timeAgo } from "@/lib/utils";

interface UserRow {
  id: number;
  email: string;
  full_name: string;
  role: string;
  hospital_id: number | null;
  hospital_name: string | null;
  mfa_enabled: boolean;
  active: boolean;
  created_at: string;
}
interface Dataset {
  filename: string;
  n_rows: number;
  n_positive: number;
  sha256: string;
  uploaded_at: string;
}
interface Hospital {
  id: number;
  code: string;
  name: string;
  city: string;
  active: boolean;
  // platform admin only: counts, never patient data
  decommissioned_at?: string | null;
  n_users?: number;
  n_patients?: number;
  dataset?: Dataset | null;
  n_training?: number;
}

// Mirrors ASSIGNABLE in backend/app/routers/admin.py (the server enforces it): one platform admin, who appoints
// hospital admins; each hospital admin appoints that hospital's clinicians.
const ASSIGNABLE: Record<string, string[]> = {
  platform_admin: ["hospital_admin", "data_scientist", "auditor"],
  hospital_admin: ["clinician", "hospital_admin"],
};
const HOSPITAL_ROLES = ["hospital_admin", "clinician"];
const canAssign = (actor: string | undefined, role: string) => (ASSIGNABLE[actor ?? ""] ?? []).includes(role);
const rolesFor = (actor: string | undefined, atHospital: boolean, current: string) => {
  const ok = (ASSIGNABLE[actor ?? ""] ?? []).filter((r) => HOSPITAL_ROLES.includes(r) === atHospital);
  return ok.includes(current) ? ok : [current, ...ok];
};

export default function AdminPage() {
  const { user, can } = useAuth();
  const users = useApi<UserRow[]>("/users");
  const hospitals = useApi<Hospital[]>("/hospitals");
  const [newUser, setNewUser] = useState(false);
  const [newHosp, setNewHosp] = useState(false);
  const [deactivating, setDeactivating] = useState<Hospital | null>(null);
  const [deleting, setDeleting] = useState<Hospital | null>(null);
  const [resetting, setResetting] = useState<UserRow | null>(null);

  async function reactivate(h: Hospital) {
    try {
      await api(`/hospitals/${h.id}/reactivate`, { method: "POST" });
      toast.success(`${h.name} re-activated`);
      hospitals.reload();
    } catch (e) {
      toast.error("Could not re-activate", { description: (e as Error).message });
    }
  }

  async function patch(u: UserRow, body: Partial<UserRow>, msg: string) {
    const prev = users.data;
    users.setData(prev?.map((x) => (x.id === u.id ? { ...x, ...body } : x)) ?? null); // optimistic
    try {
      await api(`/users/${u.id}`, { method: "PATCH", json: body });
      toast.success(msg, {
        action: body.active === false ? { label: "Undo", onClick: () => patch({ ...u, active: false }, { active: true }, "Re-activated") } : undefined,
      });
    } catch (e) {
      users.setData(prev);
      toast.error("Update failed", { description: (e as Error).message });
    }
  }

  return (
    <>
      <PageHeader eyebrow={<Badge tone="accent"><ShieldCheck /> Least privilege · deny by default</Badge>} title="Administration"
        description={user?.role === "platform_admin" ? "Manage hospitals and accounts across the platform. Platform admins cannot read patient data." : `Manage accounts at ${user?.hospital_name}.`}
        actions={<><Button variant="secondary" onClick={() => setNewUser(true)}><UserPlus /> Add user</Button>{can("hospital:manage") && <Button onClick={() => setNewHosp(true)}><Plus /> Add hospital</Button>}</>} />
      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users"><Users /> Users</TabsTrigger>
          <TabsTrigger value="hospitals"><Building2 /> Hospitals</TabsTrigger>
          {can("dataset:manage") && <TabsTrigger value="data"><Database /> Training data</TabsTrigger>}
          <TabsTrigger value="roles"><ShieldCheck /> Roles</TabsTrigger>
        </TabsList>
        <TabsContent value="users">
          <Card><CardBody>
            {users.loading ? <LoadingRows /> : users.error ? <ErrorState error={users.error} onRetry={() => users.reload()} /> : (
              <Table>
                <thead><tr><Th>User</Th><Th>Role</Th><Th>Hospital</Th><Th>MFA</Th><Th>Status</Th><Th>Created</Th><Th className="text-right">Actions</Th></tr></thead>
                <tbody>
                  {users.data!.map((u) => (
                    <tr key={u.id} className="hover:bg-surface-2/50">
                      <Td><div className="font-medium">{u.full_name}</div><div className="text-[12px] text-muted">{u.email}</div></Td>
                      <Td>
                        <NativeSelect aria-label={`Role for ${u.full_name}`} className="h-8 w-40 text-[12.5px]" value={u.role}
                          disabled={u.id === user?.id || !canAssign(user?.role, u.role)}
                          onChange={(e) => patch(u, { role: e.target.value }, "Role updated")}>
                          {rolesFor(user?.role, u.hospital_id !== null, u.role).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                        </NativeSelect>
                      </Td>
                      <Td className="text-[13px]">{u.hospital_name ?? <span className="text-subtle">—</span>}</Td>
                      <Td>{u.mfa_enabled ? <Badge tone="success">on</Badge> : <Badge>off</Badge>}</Td>
                      <Td>{u.active ? <Badge tone="success">active</Badge> : <Badge tone="danger">disabled</Badge>}</Td>
                      <Td className="text-[12.5px] text-muted">{timeAgo(u.created_at)}</Td>
                      <Td className="text-right">
                        {u.id !== user?.id && canAssign(user?.role, u.role) && (
                          <Button size="sm" variant="ghost" onClick={() => setResetting(u)}>Reset password</Button>
                        )}
                        {u.id !== user?.id && (
                          <Button size="sm" variant="ghost" className={u.active ? "text-danger" : ""} onClick={() => patch(u, { active: !u.active }, u.active ? "User deactivated" : "User re-activated")}>
                            {u.active ? "Deactivate" : "Activate"}
                          </Button>
                        )}
                        {u.id === user?.id && <MoreHorizontal className="ml-auto size-4 text-subtle" aria-label="You" />}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </CardBody></Card>
        </TabsContent>
        <TabsContent value="hospitals">
          {hospitals.loading ? <LoadingRows /> : hospitals.error ? <ErrorState error={hospitals.error} onRetry={() => hospitals.reload()} /> : !hospitals.data!.length ? (
            <EmptyState icon={<Building2 />} title="No hospitals yet" description="Add a hospital, then create its hospital admin. The admin uploads the hospital's training data."
              action={can("hospital:manage") && <Button onClick={() => setNewHosp(true)}><Plus /> Add hospital</Button>} />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {hospitals.data!.map((h) => (
                <Card key={h.id} className={h.active ? "flex flex-col p-5" : "flex flex-col p-5 opacity-75"}>
                  <div className="flex items-start justify-between">
                    <div className="grid size-10 place-items-center rounded-xl bg-primary-soft text-primary"><Building2 className="size-5" /></div>
                    {h.active ? <Badge tone="success">active</Badge> : <Badge tone="danger">deactivated</Badge>}
                  </div>
                  <div className="mt-3 font-semibold">{h.name}</div>
                  <div className="text-[12.5px] text-muted">{h.city}</div>
                  <div className="mt-3 font-mono text-[11px] text-subtle">tenant: {h.code}</div>
                  {h.n_users !== undefined && (
                    <dl className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
                      <div><dt className="text-muted">Users</dt><dd className="tabular font-semibold">{h.n_users}</dd></div>
                      <div><dt className="text-muted">Patients</dt><dd className="tabular font-semibold">{h.n_patients}</dd></div>
                      <div><dt className="text-muted">Training rows</dt><dd className="tabular font-semibold">{h.n_training ? h.n_training : <span className="font-normal text-warning">none</span>}</dd></div>
                    </dl>
                  )}
                  {can("hospital:manage") && (
                    <div className="mt-auto flex flex-wrap gap-2 border-t border-border pt-3">
                      {h.active ? (
                        <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeactivating(h)}><Power /> Deactivate</Button>
                      ) : (
                        <>
                          <Button size="sm" variant="secondary" onClick={() => reactivate(h)}><RotateCcw /> Re-activate</Button>
                          <Button size="sm" variant="ghost" className="text-danger" onClick={() => setDeleting(h)}><Trash2 /> Delete</Button>
                        </>
                      )}
                    </div>
                  )}
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        {can("dataset:manage") && <TabsContent value="data"><TrainingData /></TabsContent>}
        <TabsContent value="roles"><RolesMatrix /></TabsContent>
      </Tabs>
      <NewUserDialog open={newUser} onOpenChange={setNewUser} hospitals={hospitals.data ?? []} onDone={() => users.reload()} />
      <NewHospitalDialog open={newHosp} onOpenChange={setNewHosp} onDone={() => hospitals.reload()} />
      <DeactivateDialog hospital={deactivating} onClose={() => setDeactivating(null)} onDone={() => { hospitals.reload(); users.reload(); }} />
      <DeleteDialog hospital={deleting} onClose={() => setDeleting(null)} onDone={() => { hospitals.reload(); users.reload(); }} />
      <ResetPasswordDialog target={resetting} onClose={() => setResetting(null)} />
    </>
  );
}

const MATRIX: [string, string[]][] = [
  ["Read own hospital's patients", ["hospital_admin", "clinician"]],
  ["Risk prediction", ["clinician"]],
  ["Request shared records", ["clinician"]],
  ["Approve / revoke sharing", ["hospital_admin"]],
  ["Upload own hospital's training data", ["hospital_admin"]],
  ["Launch federated training", ["data_scientist"]],
  ["View experiments & models", ["platform_admin", "hospital_admin", "clinician", "data_scientist", "auditor"]],
  ["Promote / roll back models", ["platform_admin"]],
  ["View audit log", ["platform_admin", "hospital_admin", "auditor"]],
  ["Export audit log", ["auditor"]],
  ["Appoint hospital admins", ["platform_admin"]],
  ["Add clinicians to own hospital", ["hospital_admin"]],
  ["Register patients", ["clinician"]],
  ["Add / deactivate / delete hospitals", ["platform_admin"]],
];

function RolesMatrix() {
  const roles = Object.keys(ROLE_LABEL);
  return (
    <Card>
      <CardHeader title="Role permissions" description="Enforced server-side on every endpoint; anything not listed is denied." />
      <CardBody>
        <Table>
          <thead><tr><Th>Capability</Th>{roles.map((r) => <Th key={r} className="text-center">{ROLE_LABEL[r]}</Th>)}</tr></thead>
          <tbody>
            {MATRIX.map(([cap, allowed]) => (
              <tr key={cap}>
                <Td className="text-[13px]">{cap}</Td>
                {roles.map((r) => <Td key={r} className="text-center">{allowed.includes(r) ? <span className="inline-block size-2.5 rounded-full bg-success" aria-label="allowed" /> : <span className="inline-block size-2.5 rounded-full bg-surface-3" aria-label="denied" />}</Td>)}
              </tr>
            ))}
          </tbody>
        </Table>
      </CardBody>
    </Card>
  );
}

function NewUserDialog({ open, onOpenChange, hospitals, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; hospitals: Hospital[]; onDone: () => void }) {
  const { user } = useAuth();
  const roles = ASSIGNABLE[user?.role ?? ""] ?? [];
  const [f, setF] = useState({ email: "", full_name: "", role: roles[0] ?? "clinician", hospital_id: String(user?.hospital_id ?? ""), password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const atHospital = HOSPITAL_ROLES.includes(f.role);
  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await api("/users", { method: "POST", json: { ...f, hospital_id: atHospital && f.hospital_id ? Number(f.hospital_id) : null } });
      toast.success("User created");
      onOpenChange(false);
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add user"
      description={user?.role === "platform_admin"
        ? "You appoint hospital admins and platform-level staff. Each hospital admin adds their own clinicians."
        : `Add clinicians and admins for ${user?.hospital_name}. The user should enrol MFA at first sign-in.`}
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy}>Create user</Button></>}>
      <div className="grid gap-4">
        <Field label="Full name" htmlFor="u-name"><Input id="u-name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email" htmlFor="u-email"><Input id="u-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Role" htmlFor="u-role">
            <NativeSelect id="u-role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Hospital" htmlFor="u-h">
            <NativeSelect id="u-h" value={atHospital ? f.hospital_id : ""} disabled={!atHospital || user?.role !== "platform_admin"} onChange={(e) => setF({ ...f, hospital_id: e.target.value })}>
              <option value="">{atHospital ? "Choose a hospital" : "None (platform-wide)"}</option>
              {hospitals.filter((h) => h.active).map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </NativeSelect>
          </Field>
        </div>
        <Field label="Temporary password" htmlFor="u-pw" hint="At least 10 characters." error={err}><Input id="u-pw" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
      </div>
    </Dialog>
  );
}

function NewHospitalDialog({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const blank = { code: "", name: "", city: "" };
  const blankAdmin = { full_name: "", email: "", password: "" };
  const [f, setF] = useState(blank);
  const [a, setA] = useState(blankAdmin);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      await api("/hospitals", { method: "POST", json: { ...f, admin: a } });
      toast.success("Hospital added", { description: `${a.email} can now sign in and add the hospital's clinicians.` });
      setF(blank);
      setA(blankAdmin);
      onOpenChange(false);
      onDone();
    } catch (e) {
      toast.error("Could not add hospital", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add hospital"
      description="Every hospital gets its own admin, who then adds that hospital's clinicians and uploads its training data."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy}>Add</Button></>}>
      <div className="grid gap-4">
        <Field label="Hospital name" htmlFor="h-name"><Input id="h-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tenant code" htmlFor="h-code" hint="lowercase letters, digits, underscore"><Input id="h-code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toLowerCase() })} /></Field>
          <Field label="City" htmlFor="h-city"><Input id="h-city" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></Field>
        </div>
        <div className="border-t border-border pt-4 text-[13px] font-semibold">Hospital admin</div>
        <Field label="Admin's full name" htmlFor="h-aname"><Input id="h-aname" value={a.full_name} onChange={(e) => setA({ ...a, full_name: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Admin's email" htmlFor="h-aemail"><Input id="h-aemail" type="email" value={a.email} onChange={(e) => setA({ ...a, email: e.target.value })} /></Field>
          <Field label="Temporary password" htmlFor="h-apw" hint="At least 10 characters."><Input id="h-apw" type="password" value={a.password} onChange={(e) => setA({ ...a, password: e.target.value })} /></Field>
        </div>
      </div>
    </Dialog>
  );
}

function DeactivateDialog({ hospital: h, onClose, onDone }: { hospital: Hospital | null; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  async function submit() {
    if (!h) return;
    setBusy(true);
    try {
      await api(`/hospitals/${h.id}/deactivate`, { method: "POST" });
      toast.success(`${h.name} deactivated`);
      onClose();
      onDone();
    } catch (e) {
      toast.error("Could not deactivate", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!h} onOpenChange={(o) => !o && onClose()} title={`Deactivate ${h?.name ?? ""}?`}
      description="Its records are kept and you can re-activate it later."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" onClick={submit} loading={busy}><Power /> Deactivate</Button></>}>
      <ul className="list-disc space-y-1.5 pl-5 text-[13px] text-muted">
        <li>Its {h?.n_users ?? 0} accounts are signed out and cannot sign in.</li>
        <li>Its FL node goes offline, so its data leaves future training jobs.</li>
        <li>Pending and approved record shares to or from it are closed and their keys destroyed. These do not come back on re-activation.</li>
        <li>Consents that name it as the recipient are revoked.</li>
        <li>Other hospitals can no longer find its patients.</li>
      </ul>
    </Dialog>
  );
}

function DeleteDialog({ hospital: h, onClose, onDone }: { hospital: Hospital | null; onClose: () => void; onDone: () => void }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  function close() {
    setTyped("");
    onClose();
  }
  async function submit() {
    if (!h) return;
    setBusy(true);
    try {
      await api(`/hospitals/${h.id}?confirm=${encodeURIComponent(typed)}`, { method: "DELETE" });
      toast.success(`${h.name} permanently deleted`);
      close();
      onDone();
    } catch (e) {
      toast.error("Could not delete", { description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!h} onOpenChange={(o) => !o && close()} title={`Permanently delete ${h?.name ?? ""}?`}
      description="This cannot be undone."
      footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button variant="danger" onClick={submit} loading={busy} disabled={typed !== h?.code}><Trash2 /> Delete forever</Button></>}>
      <div className="grid gap-4">
        <p className="text-[13px] text-muted">
          Erases its {h?.n_patients ?? 0} patient records, their consents and shares, its training dataset, its FL node and its {h?.n_users ?? 0} accounts,
          then destroys the hospital&apos;s encryption key. The audit log is kept and records the deletion.
        </p>
        <Field label={`Type ${h?.code ?? ""} to confirm`} htmlFor="del-code">
          <Input id="del-code" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

const COLUMN_HELP: [string, string][] = [
  ["age", "years"],
  ["sex", "1 = male, 0 = female"],
  ["cp", "chest pain type 1–4 (4 = asymptomatic)"],
  ["trestbps", "resting blood pressure, mm Hg"],
  ["chol", "serum cholesterol, mg/dl"],
  ["fbs", "fasting blood sugar > 120 mg/dl: 1 or 0"],
  ["restecg", "resting ECG result 0–2"],
  ["thalach", "maximum heart rate"],
  ["exang", "exercise-induced angina: 1 or 0"],
  ["oldpeak", "ST depression"],
  ["target", "1 = heart disease, 0 = none (a UCI num column 0–4 also works)"],
];

function TrainingData() {
  const { user } = useAuth();
  const info = useApi<{
    dataset: Dataset | null; min_rows: number; min_per_class: number;
    rows_from_csv: number; rows_from_patients: number; n_training: number; n_positive: number; usable: boolean;
  }>("/datasets/mine");
  const file = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);

  async function upload(f: File) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ dataset: Dataset }>("/datasets/mine", { method: "POST", json: { filename: f.name, csv: await f.text() } });
      info.reload();
      toast.success("Training data uploaded", { description: `${r.dataset.n_rows} rows. This hospital now takes part in federated training.` });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  }
  async function template() {
    const csv = await api<string>("/datasets/template.csv");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "fedcardio-template.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  }
  async function remove() {
    try {
      await api("/datasets/mine", { method: "DELETE" });
      info.reload();
      toast.success("Training data removed");
    } catch (e) {
      toast.error("Could not remove", { description: (e as Error).message });
    } finally {
      setConfirmRemove(false);
    }
  }

  if (info.loading) return <LoadingRows />;
  if (info.error) return <ErrorState error={info.error} onRetry={() => info.reload()} />;
  const ds = info.data!.dataset;
  const t = info.data!;
  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <Card>
        <CardHeader icon={<Database />} title={`${user?.hospital_name ?? "Hospital"} training data`}
          description="Used only inside this hospital's FL node and stored encrypted with this hospital's key. Model updates leave; rows never do." />
        <CardBody className="grid gap-4">
          {ds ? (
            <dl className="grid grid-cols-2 gap-4 rounded-xl border border-border bg-surface-2 p-4 text-[13px] sm:grid-cols-4">
              <div className="min-w-0"><dt className="text-muted">File</dt><dd className="truncate font-medium">{ds.filename}</dd></div>
              <div><dt className="text-muted">Rows</dt><dd className="tabular font-semibold">{ds.n_rows.toLocaleString()}</dd></div>
              <div><dt className="text-muted">With heart disease</dt><dd className="tabular font-semibold">{Math.round((100 * ds.n_positive) / ds.n_rows)}%</dd></div>
              <div><dt className="text-muted">Uploaded</dt><dd>{timeAgo(ds.uploaded_at)}</dd></div>
              <div className="col-span-full flex min-w-0 gap-1.5 font-mono text-[11px] text-subtle"><dt>sha256</dt><dd className="truncate">{ds.sha256}</dd></div>
            </dl>
          ) : (
            <EmptyState icon={<Database />} title="No training data yet"
              description={`Upload a CSV with at least ${info.data!.min_rows} patients, including ${info.data!.min_per_class} with and ${info.data!.min_per_class} without heart disease. Until then this hospital is not part of federated training.`} />
          )}
          <div className="grid gap-1 rounded-xl border border-border p-4 text-[13px]">
            <div className="flex items-center justify-between font-semibold">
              <span>Training rows this hospital contributes</span>
              {t.usable ? <Badge tone="success">in training</Badge> : <Badge tone="warning">not enough yet</Badge>}
            </div>
            <div className="text-muted">
              {t.rows_from_csv} from the uploaded CSV + {t.rows_from_patients} registered patient{t.rows_from_patients === 1 ? "" : "s"} with a diagnosis and research consent
              = <span className="tabular font-semibold text-fg">{t.n_training}</span> ({t.n_positive} with heart disease).
              {!t.usable && ` A hospital needs ${t.min_rows} rows, with at least ${t.min_per_class} with and ${t.min_per_class} without heart disease.`}
            </div>
          </div>
          {err && <div role="alert" className="rounded-lg border border-danger/30 bg-danger-soft p-3 text-[13px] text-danger">{err}</div>}
          <div className="flex flex-wrap gap-2">
            <input ref={file} type="file" accept=".csv,text/csv" className="sr-only" aria-label="Choose CSV file" tabIndex={-1}
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
            <Button onClick={() => file.current?.click()} loading={busy}><Upload /> {ds ? "Replace CSV" : "Upload CSV"}</Button>
            <Button variant="secondary" onClick={template}><Download /> Download template</Button>
            {ds && <Button variant="ghost" className="text-danger" onClick={() => setConfirmRemove(true)}><Trash2 /> Remove</Button>}
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="CSV columns" description="Header row required. Leave a cell empty if a value was not measured." />
        <CardBody>
          <Table>
            <tbody>
              {COLUMN_HELP.map(([c, d]) => (
                <tr key={c}><Td className="font-mono text-[12px]">{c}</Td><Td className="text-[12.5px] text-muted">{d}</Td></tr>
              ))}
            </tbody>
          </Table>
        </CardBody>
      </Card>
      <Dialog open={confirmRemove} onOpenChange={setConfirmRemove} title="Remove training data?"
        description="This hospital drops out of future training jobs until new data is uploaded. Patient records are not affected."
        footer={<><Button variant="secondary" onClick={() => setConfirmRemove(false)}>Cancel</Button><Button variant="danger" onClick={remove}><Trash2 /> Remove</Button></>} />
    </div>
  );
}

function ResetPasswordDialog({ target: u, onClose }: { target: UserRow | null; onClose: () => void }) {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  function close() {
    setPw("");
    setErr(null);
    onClose();
  }
  async function submit() {
    if (!u) return;
    setBusy(true);
    setErr(null);
    try {
      await api(`/users/${u.id}/password`, { method: "POST", json: { password: pw } });
      toast.success(`New temporary password set for ${u.full_name}`, { description: "Tell them in person; they choose their own at next sign-in." });
      close();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!u} onOpenChange={(o) => !o && close()} title={`Reset password for ${u?.full_name ?? ""}`}
      description="They are signed out everywhere and must choose their own password the next time they sign in."
      footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button onClick={submit} loading={busy} disabled={pw.length < 10}>Set temporary password</Button></>}>
      <Field label="New temporary password" htmlFor="rp-pw" hint="At least 10 characters." error={err}>
        <Input id="rp-pw" type="text" autoComplete="off" value={pw} onChange={(e) => setPw(e.target.value)} />
      </Field>
    </Dialog>
  );
}
