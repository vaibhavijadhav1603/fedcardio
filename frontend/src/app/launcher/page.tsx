"use client";

import { motion } from "framer-motion";
import { ArrowRight, BookOpen, Building2, FlaskConical, Hospital, LogOut, ScrollText, ShieldCheck, Stethoscope } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/brand";
import { Button, Skeleton } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { homeFor, ROLE_LABEL, useAuth } from "@/lib/auth";

// Dev only: once the platform admin has signed in, every role is one click away, with no passwords.
interface Account { id: number; email: string; full_name: string; role: string }
interface Groups { platform: Account[]; hospitals: { id: number; name: string; city: string; users: Account[] }[] }

let cached: Groups | null = null; // shown instantly on the next visit, then refreshed

const ROLE_INFO: Record<string, { icon: typeof ShieldCheck; does: string; tone: string }> = {
  platform_admin: { icon: ShieldCheck, does: "Hospitals, staff accounts, production model", tone: "from-indigo-500 to-violet-500" },
  data_scientist: { icon: FlaskConical, does: "Launch federated training, register models", tone: "from-sky-500 to-cyan-500" },
  auditor: { icon: ScrollText, does: "Verify and export the audit log", tone: "from-amber-500 to-orange-500" },
  hospital_admin: { icon: Building2, does: "Clinicians, training data, share approvals", tone: "from-teal-500 to-emerald-500" },
  clinician: { icon: Stethoscope, does: "Patients, risk assessment, record sharing", tone: "from-rose-500 to-pink-500" },
};

export default function LauncherPage() {
  const { enterAs, signOutAll } = useAuth();
  const signOut = () => {
    cached = null;
    return signOutAll();
  };
  const router = useRouter();
  const [groups, setGroups] = useState<Groups | null>(cached);
  const [entering, setEntering] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Groups>("/auth/launcher").then(
      (g) => setGroups((cached = g)),
      () => {
        cached = null;
        router.replace("/login");
      },
    );
  }, [router]);

  async function enter(a: Account) {
    setEntering(a.id);
    setError(null);
    try {
      const u = await enterAs(a.id);
      router.replace(homeFor(u.role));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return router.replace("/login");
      setError((e as Error).message);
      setEntering(null);
    }
  }

  const card = (a: Account) => {
    const info = ROLE_INFO[a.role] ?? ROLE_INFO.clinician;
    const Icon = info.icon;
    return (
      <button
        key={a.id}
        type="button"
        onClick={() => enter(a)}
        disabled={entering !== null}
        className="group flex w-full items-center gap-3 rounded-xl border border-border bg-surface p-3.5 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md disabled:opacity-60"
      >
        <span className={`grid size-10 shrink-0 place-items-center rounded-lg bg-gradient-to-br text-white ${info.tone}`}>
          <Icon className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[14px] font-semibold">{ROLE_LABEL[a.role] ?? a.role}</span>
          <span className="block truncate text-[12.5px] text-muted">{a.full_name} · {a.email}</span>
          <span className="block truncate text-[12px] text-subtle">{info.does}</span>
        </span>
        <ArrowRight className={`size-4 shrink-0 text-subtle transition-transform group-hover:translate-x-0.5 ${entering === a.id ? "animate-pulse text-primary" : ""}`} aria-hidden />
      </button>
    );
  };

  return (
    <main className="min-h-dvh bg-bg">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-3">
            <Logo className="size-9" />
            <div>
              <div className="text-lg font-semibold tracking-tight">FedCardio</div>
              <div className="text-xs text-muted">Research demonstrator</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button asChild size="sm">
              <Link href="/about"><BookOpen /> How it works</Link>
            </Button>
            <Button variant="secondary" size="sm" onClick={signOut}>
              <LogOut /> Sign out
            </Button>
          </div>
        </div>
      </header>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        className="mx-auto max-w-6xl px-4 py-8 sm:px-6"
      >
        <h1 className="text-2xl font-semibold tracking-tight">Choose a role</h1>
        {error && <p role="alert" className="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{error}</p>}

        {!groups ? (
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}
          </div>
        ) : (
          <>
            <section className="mt-8">
              <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-subtle">Platform</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{groups.platform.map(card)}</div>
            </section>
            <section className="mt-10">
              <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-subtle">Hospitals</h2>
              <div className="grid gap-4 lg:grid-cols-2">
                {groups.hospitals.map((h) => (
                  <div key={h.id} className="rounded-2xl border border-border bg-surface-2/40 p-4">
                    <div className="mb-3 flex items-center gap-2">
                      <Hospital className="size-4 text-primary" aria-hidden />
                      <span className="text-[14px] font-semibold">{h.name}</span>
                      {h.city && <span className="text-[12.5px] text-muted">· {h.city}</span>}
                    </div>
                    {h.users.length ? (
                      <div className="grid gap-2.5">{h.users.map(card)}</div>
                    ) : (
                      <p className="text-[13px] text-muted">No accounts yet. The platform admin adds this hospital&apos;s admin.</p>
                    )}
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </motion.div>
    </main>
  );
}
