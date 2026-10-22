"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/app-shell";
import { Logo } from "@/components/brand";
import { useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);
  if (loading || !user)
    return (
      <div className="grid min-h-dvh place-items-center" role="status" aria-label="Loading session">
        <Logo className="size-10 animate-pulse" />
      </div>
    );
  return <AppShell>{children}</AppShell>;
}
