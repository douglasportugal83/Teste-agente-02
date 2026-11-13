"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

const INPUT =
  "w-full rounded-lg border border-line bg-canvas px-3 py-2.5 text-sm placeholder:text-muted/60";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { user, loading, login, register } = useAuth();
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const isRegister = mode === "register";

  useEffect(() => {
    if (!loading && user) router.replace("/dashboard");
  }, [loading, user, router]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (isRegister) await register(email, password, fullName);
      else await login(email, password);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Erro inesperado.");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="text-center text-3xl font-semibold tracking-tight">
          TraderAI <span className="text-accent">Pro</span>
        </h1>
        <p className="mt-2 text-center text-sm text-muted">
          Análise, backtesting e simulação — sem ordens reais.
        </p>

        <form onSubmit={onSubmit} className="mt-8 space-y-4 rounded-xl border border-line bg-panel p-6">
          <h2 className="text-lg font-medium">{isRegister ? "Criar conta" : "Entrar"}</h2>

          {isRegister && (
            <label className="block space-y-1.5 text-sm">
              <span>Nome</span>
              <input
                className={INPUT}
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
                maxLength={200}
              />
            </label>
          )}
          <label className="block space-y-1.5 text-sm">
            <span>E-mail</span>
            <input
              className={INPUT}
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </label>
          <label className="block space-y-1.5 text-sm">
            <span>Senha</span>
            <input
              className={INPUT}
              type="password"
              required
              minLength={isRegister ? 8 : 1}
              maxLength={128}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isRegister ? "new-password" : "current-password"}
            />
            {isRegister && (
              <span className="block text-xs text-muted">
                Mínimo de 8 caracteres, combinando letras e números ou símbolos.
              </span>
            )}
          </label>

          {error && (
            <p role="alert" className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-ink disabled:opacity-60"
          >
            {submitting ? "Aguarde…" : isRegister ? "Criar conta" : "Entrar"}
          </button>

          <p className="text-center text-sm text-muted">
            {isRegister ? "Já tem conta? " : "Ainda não tem conta? "}
            <Link href={isRegister ? "/login" : "/register"} className="text-accent underline">
              {isRegister ? "Entrar" : "Criar conta"}
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
