"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, refreshSession, setAccessToken, setOnUnauthorized, type Me } from "./api";

interface AuthState {
  user: Me | null;
  loading: boolean;
  can: (perm: string) => boolean;
  login: (email: string, password: string) => Promise<{ mfa: false } | { mfa: true; challenge: string }>;
  verifyMfa: (challenge: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  /** Dev role launcher: open once the platform admin has signed in; enter any account without a password. */
  launcher: boolean;
  enterAs: (userId: number) => Promise<Me>;
  switchRole: () => void;
  signOutAll: () => Promise<void>;
}

let leaving: Promise<unknown> = Promise.resolve(); // sign-out of the role being left, still in flight

const launcherOpen = () =>
  fetch("/api/auth/launcher", { credentials: "same-origin" }).then((r) => r.ok, () => false);

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [launcher, setLauncher] = useState(false);
  const router = useRouter();

  useEffect(() => {
    setOnUnauthorized(() => {
      setUser(null);
      setAccessToken(null);
      router.replace("/login?expired=1");
    });
    Promise.all([refreshSession().then((s) => setUser(s?.user ?? null)), launcherOpen().then(setLauncher)])
      .finally(() => setLoading(false));
  }, [router]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ access_token?: string; user?: Me; mfa_required?: boolean; challenge?: string }>(
      "/auth/login",
      { method: "POST", json: { email, password } },
    );
    if (r.mfa_required && r.challenge) return { mfa: true as const, challenge: r.challenge };
    setAccessToken(r.access_token!);
    setLauncher(await launcherOpen());
    setUser(r.user!);
    return { mfa: false as const };
  }, []);

  const verifyMfa = useCallback(async (challenge: string, code: string) => {
    const r = await api<{ access_token: string; user: Me }>("/auth/mfa/verify", {
      method: "POST",
      json: { challenge, code },
    });
    setAccessToken(r.access_token);
    setLauncher(await launcherOpen());
    setUser(r.user);
  }, []);

  // leaving a role with the launcher open goes back to the role picker instead of the sign-in page
  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
      setUser(null);
      router.replace(launcher ? "/launcher" : "/login");
    }
  }, [router, launcher]);

  const enterAs = useCallback(async (userId: number) => {
    await leaving; // its cookie deletion must not land after the new session's cookie
    const r = await api<{ access_token: string; user: Me }>("/auth/launcher/enter", { method: "POST", json: { user_id: userId } });
    setAccessToken(r.access_token);
    setUser(r.user);
    return r.user;
  }, []);

  // Straight to the role picker: the old role's session is ended in the background (entering the next
  // role revokes it anyway), so the app never flashes the sign-in page on the way.
  const switchRole = useCallback(() => {
    router.replace("/launcher");
    leaving = api("/auth/logout", { method: "POST" }).catch(() => undefined);
  }, [router]);

  const signOutAll = useCallback(async () => {
    try {
      await api("/auth/launcher/close", { method: "POST" });
    } finally {
      setAccessToken(null);
      setUser(null);
      setLauncher(false);
      router.replace("/login");
    }
  }, [router]);

  const refreshUser = useCallback(async () => setUser(await api<Me>("/auth/me")), []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      can: (p) => !!user?.permissions.includes(p),
      login,
      verifyMfa,
      logout,
      refreshUser,
      launcher,
      enterAs,
      switchRole,
      signOutAll,
    }),
    [user, loading, login, verifyMfa, logout, refreshUser, launcher, enterAs, switchRole, signOutAll],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

export const ROLE_LABEL: Record<string, string> = {
  platform_admin: "Platform admin",
  hospital_admin: "Hospital admin",
  clinician: "Clinician",
  data_scientist: "Data scientist",
  auditor: "Auditor",
};

export function homeFor(role?: string) {
  switch (role) {
    case "clinician":
      return "/risk";
    case "data_scientist":
      return "/federated";
    case "auditor":
      return "/audit";
    case "hospital_admin":
      return "/sharing";
    default:
      return "/results";
  }
}
