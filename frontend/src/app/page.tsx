"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Logo } from "@/components/brand";
import { homeFor, useAuth } from "@/lib/auth";

export default function Home() {
  const { user, loading, launcher } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading) router.replace(user ? homeFor(user.role) : launcher ? "/launcher" : "/login");
  }, [user, loading, launcher, router]);
  return (
    <div className="grid min-h-dvh place-items-center" role="status" aria-label="Loading">
      <Logo className="size-10 animate-pulse" />
    </div>
  );
}
