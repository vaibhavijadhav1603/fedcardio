"use client";

import { Building2, MoreHorizontal, Plus, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import {
  Badge, Button, Card, CardBody, CardHeader, Dialog, ErrorState, Field, Input, LoadingRows, NativeSelect, PageHeader,
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
interface Hospital {
  id: number;
  code: string;
  name: string;
  city: string;
}

export default function AdminPage() {
  const { user, can } = useAuth();
  const users = useApi<UserRow[]>("/users");
  const hospitals = useApi<Hospital[]>("/hospitals");
  const [newUser, setNewUser] = useState(false);
  const [newHosp, setNewHosp] = useState(false);

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
                        <NativeSelect aria-label={`Role for ${u.full_name}`} className="h-8 w-40 text-[12.5px]" value={u.role} disabled={u.id === user?.id}
                          onChange={(e) => patch(u, { role: e.target.value }, "Role updated")}>
                          {Object.entries(ROLE_LABEL).filter(([r]) => r !== "platform_admin" || user?.role === "platform_admin").map(([r, l]) => <option key={r} value={r}>{l}</option>)}
                        </NativeSelect>
                      </Td>
                      <Td className="text-[13px]">{u.hospital_name ?? <span className="text-subtle">—</span>}</Td>
                      <Td>{u.mfa_enabled ? <Badge tone="success">on</Badge> : <Badge>off</Badge>}</Td>
                      <Td>{u.active ? <Badge tone="success">active</Badge> : <Badge tone="danger">disabled</Badge>}</Td>
                      <Td className="text-[12.5px] text-muted">{timeAgo(u.created_at)}</Td>
                      <Td className="text-right">
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
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {hospitals.data?.map((h) => (
              <Card key={h.id} className="p-5">
                <div className="grid size-10 place-items-center rounded-xl bg-primary-soft text-primary"><Building2 className="size-5" /></div>
                <div className="mt-3 font-semibold">{h.name}</div>
                <div className="text-[12.5px] text-muted">{h.city}</div>
                <div className="mt-3 font-mono text-[11px] text-subtle">tenant: {h.code}</div>
              </Card>
            ))}
          </div>
        </TabsContent>
        <TabsContent value="roles"><RolesMatrix /></TabsContent>
      </Tabs>
      <NewUserDialog open={newUser} onOpenChange={setNewUser} hospitals={hospitals.data ?? []} onDone={() => users.reload()} />
      <NewHospitalDialog open={newHosp} onOpenChange={setNewHosp} onDone={() => hospitals.reload()} />
    </>
  );
}

const MATRIX: [string, string[]][] = [
  ["Read own hospital's patients", ["hospital_admin", "clinician"]],
  ["Risk prediction", ["clinician"]],
  ["Request shared records", ["clinician"]],
  ["Approve / revoke sharing", ["hospital_admin"]],
  ["Launch federated training", ["data_scientist"]],
  ["View experiments & models", ["platform_admin", "hospital_admin", "clinician", "data_scientist", "auditor"]],
  ["Promote / roll back models", ["platform_admin"]],
  ["View audit log", ["platform_admin", "hospital_admin", "auditor"]],
  ["Export audit log", ["auditor"]],
  ["Manage users", ["platform_admin", "hospital_admin"]],
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
  const [f, setF] = useState({ email: "", full_name: "", role: "clinician", hospital_id: String(user?.hospital_id ?? ""), password: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await api("/users", { method: "POST", json: { ...f, hospital_id: f.hospital_id ? Number(f.hospital_id) : null } });
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
    <Dialog open={open} onOpenChange={onOpenChange} title="Add user" description="The user should enrol MFA at first sign-in."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy}>Create user</Button></>}>
      <div className="grid gap-4">
        <Field label="Full name" htmlFor="u-name"><Input id="u-name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email" htmlFor="u-email"><Input id="u-email" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Role" htmlFor="u-role">
            <NativeSelect id="u-role" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {Object.entries(ROLE_LABEL).filter(([r]) => r !== "platform_admin" || user?.role === "platform_admin").map(([r, l]) => <option key={r} value={r}>{l}</option>)}
            </NativeSelect>
          </Field>
          <Field label="Hospital" htmlFor="u-h">
            <NativeSelect id="u-h" value={f.hospital_id} disabled={user?.role !== "platform_admin"} onChange={(e) => setF({ ...f, hospital_id: e.target.value })}>
              <option value="">None (platform)</option>
              {hospitals.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
            </NativeSelect>
          </Field>
        </div>
        <Field label="Temporary password" htmlFor="u-pw" hint="At least 10 characters." error={err}><Input id="u-pw" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
      </div>
    </Dialog>
  );
}

function NewHospitalDialog({ open, onOpenChange, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const [f, setF] = useState({ code: "", name: "", city: "" });
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      await api("/hospitals", { method: "POST", json: f });
      toast.success("Hospital added");
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
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button onClick={submit} loading={busy}>Add</Button></>}>
      <div className="grid gap-4">
        <Field label="Name" htmlFor="h-name"><Input id="h-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Tenant code" htmlFor="h-code" hint="lowercase letters, digits, underscore"><Input id="h-code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toLowerCase() })} /></Field>
        <Field label="City" htmlFor="h-city"><Input id="h-city" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} /></Field>
      </div>
    </Dialog>
  );
}
