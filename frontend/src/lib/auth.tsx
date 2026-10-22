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
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    setOnUnauthorized(() => {
      setUser(null);
      setAccessToken(null);
      router.replace("/login?expired=1");
    });
    refreshSession()
      .then((s) => setUser(s?.user ?? null))
      .finally(() => setLoading(false));
  }, [router]);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ access_token?: string; user?: Me; mfa_required?: boolean; challenge?: string }>(
      "/auth/login",
      { method: "POST", json: { email, password } },
    );
    if (r.mfa_required && r.challenge) return { mfa: true as const, challenge: r.challenge };
    setAccessToken(r.access_token!);
    setUser(r.user!);
    return { mfa: false as const };
  }, []);

  const verifyMfa = useCallback(async (challenge: string, code: string) => {
    const r = await api<{ access_token: string; user: Me }>("/auth/mfa/verify", {
      method: "POST",
      json: { challenge, code },
    });
    setAccessToken(r.access_token);
    setUser(r.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
      setUser(null);
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
    }),
    [user, loading, login, verifyMfa, logout, refreshUser],
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
