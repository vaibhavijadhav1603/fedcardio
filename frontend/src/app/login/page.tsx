"use client";

import { motion } from "framer-motion";
import { ArrowRight, Eye, EyeOff, KeyRound, Lock, ShieldCheck, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { FederationArt, Logo } from "@/components/brand";
import { Badge, Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

const DEMO = [
  { role: "Clinician", email: "dr.cleveland@fedcardio.dev" },
  { role: "Hospital admin", email: "admin.hungarian@fedcardio.dev" },
  { role: "Data scientist", email: "ds@fedcardio.dev" },
  { role: "Auditor", email: "auditor@fedcardio.dev" },
  { role: "Platform admin", email: "admin@fedcardio.dev" },
];

function LoginInner() {
  const { m } = useI18n();
  const { login, verifyMfa, user, loading } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!loading && user) router.replace(homeFor(user.role));
  }, [user, loading, router]);
  useEffect(() => {
    if (challenge) codeRef.current?.focus();
  }, [challenge]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (challenge) {
        await verifyMfa(challenge, code);
      } else {
        const r = await login(email.trim(), password);
        if (r.mfa) {
          setChallenge(r.challenge);
          setBusy(false);
          return;
        }
      }
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? "Too many attempts — wait a minute." : (err as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-dvh lg:grid-cols-[1.05fr_1fr]">
      {/* brand panel */}
      <section
        className="relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-between p-10 text-white"
        style={{ background: "linear-gradient(135deg, #0b4f4a 0%, #0f766e 45%, #3730a3 100%)" }}
      >
        <div className="bg-grid absolute inset-0 opacity-20" aria-hidden />
        <div className="relative flex items-center gap-3">
          <div className="rounded-xl bg-white/10 p-1 ring-1 ring-white/20">
            <Logo className="size-9" />
          </div>
          <div>
            <div className="text-lg font-semibold tracking-tight">FedCardio</div>
            <div className="text-xs text-white/70">Research demonstrator</div>
          </div>
        </div>
        <div className="relative flex flex-1 items-center justify-center py-8">
          <FederationArt />
        </div>
        <div className="relative space-y-5">
          <h2 className="max-w-md text-[28px] font-semibold leading-tight tracking-tight">
            Train together. Keep patient data where it belongs.
          </h2>
          <ul className="grid max-w-lg gap-3 text-sm text-white/85">
            {[
              [ShieldCheck, "Federated learning across hospitals — raw records never leave the site"],
              [Lock, "Homomorphic encryption & secure aggregation hide each hospital’s update"],
              [Sparkles, "Differential privacy with a formal (ε, δ) budget"],
            ].map(([Icon, t], i) => {
              const I = Icon as typeof ShieldCheck;
              return (
                <li key={i} className="flex items-start gap-2.5">
                  <I className="mt-0.5 size-4 shrink-0 text-teal-200" aria-hidden />
                  {t as string}
                </li>
              );
            })}
          </ul>
        </div>
      </section>

      {/* form */}
      <section className="flex items-center justify-center px-6 py-12">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: "easeOut" }}
          className="w-full max-w-sm"
        >
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Logo className="size-9" />
            <span className="text-lg font-semibold">FedCardio</span>
          </div>
          {params.get("expired") && (
            <div role="status" className="mb-5 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning">
              {m.login.expired}
            </div>
          )}
          <h1 className="text-2xl font-semibold tracking-tight">{challenge ? m.login.mfaTitle : m.login.title}</h1>
          <p className="mt-1.5 text-sm text-muted">{challenge ? m.login.mfaSubtitle : m.login.subtitle}</p>

          <form onSubmit={submit} className="mt-7 space-y-4" noValidate>
            {!challenge ? (
              <>
                <Field label={m.login.email} htmlFor="email">
                  <Input
                    id="email"
                    type="email"
                    autoComplete="username"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@hospital.org"
                    aria-invalid={!!error}
                  />
                </Field>
                <Field label={m.login.password} htmlFor="password">
                  <div className="relative">
                    <Input
                      id="password"
                      type={show ? "text" : "password"}
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="pr-10"
                      aria-invalid={!!error}
                    />
                    <button
                      type="button"
                      onClick={() => setShow((s) => !s)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-subtle hover:text-fg"
                      aria-label={show ? "Hide password" : "Show password"}
                    >
                      {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                </Field>
              </>
            ) : (
              <Field label="Authentication code" htmlFor="code">
                <Input
                  id="code"
                  ref={codeRef}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  pattern="\d{6}"
                  maxLength={6}
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                  className="tabular h-12 text-center text-xl tracking-[0.5em]"
                />
              </Field>
            )}
            {error && (
              <p role="alert" className="rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">
                {error}
              </p>
            )}
            <Button type="submit" size="lg" className="w-full" loading={busy} disabled={challenge ? code.length !== 6 : !email || !password}>
              {challenge ? (
                <>
                  <KeyRound /> {m.login.verify}
                </>
              ) : (
                <>
                  {m.login.submit} <ArrowRight />
                </>
              )}
            </Button>
            {challenge && (
              <Button type="button" variant="ghost" className="w-full" onClick={() => setChallenge(null)}>
                Use a different account
              </Button>
            )}
          </form>

          {!challenge && (
            <div className="mt-10 rounded-xl border border-border bg-surface p-4">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-semibold">{m.login.demo}</span>
                <Badge tone="warning">synthetic data</Badge>
              </div>
              <p className="mt-1 text-xs text-muted">
                Password for all: <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-fg">FedCardio!2026</code>
              </p>
              <div className="mt-3 grid gap-1.5">
                {DEMO.map((d) => (
                  <button
                    key={d.email}
                    type="button"
                    onClick={() => {
                      setEmail(d.email);
                      setPassword("FedCardio!2026");
                    }}
                    className="flex items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors hover:bg-surface-2"
                  >
                    <span className="font-medium">{d.role}</span>
                    <span className="truncate pl-3 text-xs text-muted">{d.email}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      </section>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginInner />
    </Suspense>
  );
}
