"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/lib/auth";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        {loading ? "Carregando sessão…" : "Redirecionando para o login…"}
      </div>
    );
  }
  return <AppShell>{children}</AppShell>;
}
