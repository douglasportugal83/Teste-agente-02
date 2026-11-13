"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

/** O terminal ocupa a tela inteira (sem a navegação lateral), mas exige sessão como o resto. */
export default function TerminalLayout({ children }: { children: React.ReactNode }) {
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
  return <>{children}</>;
}
