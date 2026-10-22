"use client";

import { ArrowDownToLine, CheckCircle2, Filter, Link2, ScrollText, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  Badge, Button, Card, CardBody, CardHeader, Dialog, EmptyState, ErrorState, Input, LoadingRows, NativeSelect, PageHeader,
  Table, Td, Th,
} from "@/components/ui";
import { download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { fmtDate } from "@/lib/utils";

interface Ev {
  seq: number;
  ts: string;
  actor_email: string;
  actor_role: string;
  hospital_id: number | null;
  action: string;
  resource: string;
  outcome: string;
  detail: Record<string, unknown>;
  hash: string;
  prev_hash: string;
}

const ACTIONS = ["", "auth.", "patient.", "share.", "consent.", "model.", "fl.", "user.", "audit."];

export default function AuditPage() {
  const { can } = useAuth();
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [debActor, setDebActor] = useState("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(0);
  const [open, setOpen] = useState<Ev | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebActor(actor), 300);
    return () => clearTimeout(t);
  }, [actor]);
  useEffect(() => setPage(0), [action, debActor, outcome]);
  const qs = `action=${encodeURIComponent(action)}&actor=${encodeURIComponent(debActor)}&outcome=${outcome}&limit=50&offset=${page * 50}`;
  const log = useApi<{ total: number; items: Ev[] }>(`/audit?${qs}`);
  const chain = useApi<{ valid: boolean; events_checked: number; head?: string; first_bad_seq?: number }>("/audit/verify");

  return (
    <>
      <PageHeader eyebrow={<Badge tone="primary"><ScrollText /> Append-only · SHA-256 hash chain</Badge>} title="Audit log"
        description="Every sign-in, record access, share, consent change, prediction and training job is recorded. Each entry's hash covers the previous one, so any edit or deletion is detectable."
        actions={can("audit:export") && <Button variant="secondary" onClick={() => download(`/audit/export.csv?action=${action}&actor=${debActor}&outcome=${outcome}`, "audit_log.csv").then(() => toast.success("Export downloaded")).catch((e) => toast.error(e.message))}><ArrowDownToLine /> Export CSV</Button>} />

      <Card className="mb-6">
        <CardBody className="flex flex-wrap items-center gap-4">
          {chain.loading ? <LoadingRows rows={1} /> : chain.data?.valid ? (
            <>
              <div className="grid size-11 place-items-center rounded-xl bg-success-soft text-success"><ShieldCheck className="size-5" /></div>
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-success">Chain intact</div>
                <div className="text-[12.5px] text-muted">{chain.data.events_checked.toLocaleString()} events verified · head <span className="font-mono">{chain.data.head?.slice(0, 20)}…</span></div>
              </div>
            </>
          ) : chain.data ? (
            <>
              <div className="grid size-11 place-items-center rounded-xl bg-danger-soft text-danger"><ShieldAlert className="size-5" /></div>
              <div className="flex-1"><div className="font-semibold text-danger">Tampering detected</div><div className="text-[12.5px] text-muted">Chain breaks at event #{chain.data.first_bad_seq}.</div></div>
            </>
          ) : null}
          <Button variant="secondary" size="sm" onClick={() => chain.reload()}><CheckCircle2 /> Re-verify</Button>
        </CardBody>
      </Card>

      <Card>
        <CardHeader icon={<Filter />} title="Events" description={log.data ? `${log.data.total.toLocaleString()} matching events` : undefined}
          action={
            <div className="flex flex-wrap gap-2">
              <NativeSelect aria-label="Filter by action" className="h-9 w-40" value={action} onChange={(e) => setAction(e.target.value)}>
                {ACTIONS.map((a) => <option key={a} value={a}>{a ? a.replace(".", "") : "All actions"}</option>)}
              </NativeSelect>
              <NativeSelect aria-label="Filter by outcome" className="h-9 w-36" value={outcome} onChange={(e) => setOutcome(e.target.value)}>
                <option value="">Any outcome</option><option value="success">Success</option><option value="failure">Failure</option><option value="denied">Denied</option>
              </NativeSelect>
              <Input aria-label="Filter by actor" placeholder="Actor email…" className="h-9 w-48" value={actor} onChange={(e) => setActor(e.target.value)} />
            </div>
          } />
        <CardBody>
          {log.loading && !log.data ? <LoadingRows rows={8} /> : log.error ? <ErrorState error={log.error} onRetry={() => log.reload()} /> : !log.data?.items.length ? (
            <EmptyState icon={<ScrollText />} title="No events match these filters" />
          ) : (
            <>
              <Table>
                <thead><tr><Th>#</Th><Th>Time</Th><Th>Actor</Th><Th>Action</Th><Th>Resource</Th><Th>Outcome</Th><Th>Hash</Th></tr></thead>
                <tbody>
                  {log.data.items.map((e) => (
                    <tr key={e.seq} className="cursor-pointer hover:bg-surface-2/60" onClick={() => setOpen(e)} tabIndex={0} onKeyDown={(k) => k.key === "Enter" && setOpen(e)}>
                      <Td className="tabular text-[12px] text-muted">{e.seq}</Td>
                      <Td className="whitespace-nowrap text-[12.5px]">{fmtDate(e.ts)}</Td>
                      <Td><div className="text-[12.5px] font-medium">{e.actor_email}</div><div className="text-[11px] text-muted">{e.actor_role}</div></Td>
                      <Td><Badge tone={e.action.startsWith("share") ? "accent" : e.action.startsWith("model") ? "primary" : "neutral"}>{e.action}</Badge></Td>
                      <Td className="max-w-56 truncate font-mono text-[11.5px]">{e.resource || "—"}</Td>
                      <Td><Badge tone={e.outcome === "success" ? "success" : "danger"}>{e.outcome}</Badge></Td>
                      <Td className="font-mono text-[11px] text-subtle">{e.hash.slice(0, 10)}…</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <div className="mt-4 flex items-center justify-between text-[12.5px] text-muted">
                <span>Page {page + 1} of {Math.max(1, Math.ceil(log.data.total / 50))}</span>
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
                  <Button size="sm" variant="secondary" disabled={(page + 1) * 50 >= log.data.total} onClick={() => setPage(page + 1)}>Next</Button>
                </div>
              </div>
            </>
          )}
        </CardBody>
      </Card>
      <Dialog open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={`Event #${open?.seq}`} description={open ? `${open.action} · ${fmtDate(open.ts)}` : undefined} wide>
        {open && (
          <div className="space-y-3 text-[13px]">
            <pre className="scrollbar-thin max-h-60 overflow-auto rounded-xl bg-surface-2 p-3 font-mono text-[11.5px]">{JSON.stringify(open.detail, null, 2)}</pre>
            <div className="space-y-1 rounded-xl border border-border p-3 font-mono text-[11px]">
              <div className="flex items-center gap-2 text-muted"><Link2 className="size-3.5" /> prev {open.prev_hash}</div>
              <div className="flex items-center gap-2"><Link2 className="size-3.5 text-primary" /> hash {open.hash}</div>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
