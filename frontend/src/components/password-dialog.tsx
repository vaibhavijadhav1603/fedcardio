"use client";

import { KeyRound } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button, Dialog, Field, Input } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Change your own password. `forced` = signed in with an admin-issued temporary password: cannot be dismissed. */
export function ChangePasswordDialog({ open, onOpenChange, forced = false }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  forced?: boolean;
}) {
  const { refreshUser, logout } = useAuth();
  const blank = { current: "", next: "", again: "" };
  const [f, setF] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const mismatch = f.again !== "" && f.next !== f.again;

  async function submit() {
    if (f.next.length < 5) return setErr("The new password needs at least 5 characters.");
    if (f.next !== f.again) return setErr("The two new passwords do not match.");
    setBusy(true);
    setErr(null);
    try {
      await api("/auth/password", { method: "POST", json: { current_password: f.current, new_password: f.next } });
      await refreshUser();
      toast.success("Password changed", { description: "Other sessions of this account were signed out." });
      setF(blank);
      onOpenChange(false);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !forced && onOpenChange(o)} dismissible={!forced}
      title={forced ? "Choose your own password" : "Change password"}
      description={forced ? "You signed in with a temporary password from your administrator. Set your own before continuing." : undefined}
      footer={<>
        {forced ? <Button variant="secondary" onClick={logout}>Sign out</Button> : <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>}
        <Button onClick={submit} loading={busy}><KeyRound /> Save password</Button>
      </>}>
      <form className="grid gap-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <Field label={forced ? "Temporary password" : "Current password"} htmlFor="pw-cur">
          <Input id="pw-cur" type="password" autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} />
        </Field>
        <Field label="New password" htmlFor="pw-new" hint="At least 5 characters.">
          <Input id="pw-new" type="password" autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} />
        </Field>
        <Field label="Repeat new password" htmlFor="pw-again" error={mismatch ? "Does not match." : err}>
          <Input id="pw-again" type="password" autoComplete="new-password" value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} />
        </Field>
        <button type="submit" hidden aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  );
}
