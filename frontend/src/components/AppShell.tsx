"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { useLiveStatus } from "@/lib/useLiveStatus";
import { StatusBadge } from "@/components/ui";

const NAV = [
  { href: "/dashboard", label: "Visão Geral" },
  { href: "/charts", label: "Gráficos" },
  { href: "/strategies", label: "Estratégias" },
  { href: "/simulator", label: "Robô Simulador" },
  { href: "/backtesting", label: "Backtesting" },
  { href: "/ai", label: "Inteligência Artificial" },
  { href: "/risk", label: "Gestão de Risco" },
  { href: "/admin", label: "Administração", permission: "admin:users" },
];

const LIVE_LABELS = { online: "Tempo real", connecting: "Conectando", offline: "Sem conexão" };

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout, can } = useAuth();
  const live = useLiveStatus();
  const [menuOpen, setMenuOpen] = useState(false);

  const items = NAV.filter((item) => !item.permission || can(item.permission));

  return (
    <div className="flex min-h-screen flex-col">
      <div className="bg-warn px-4 py-1.5 text-center text-xs font-semibold text-black">
        MODO SIMULAÇÃO — capital fictício, nenhuma ordem real é enviada
      </div>

      <div className="flex flex-1 flex-col md:flex-row">
        <aside className="border-line bg-panel md:w-60 md:shrink-0 md:border-r">
          <div className="flex items-center justify-between px-5 py-4">
            <Link href="/dashboard" className="text-lg font-semibold tracking-tight">
              TraderAI <span className="text-accent">Pro</span>
            </Link>
            <button
              className="rounded-md border border-line px-3 py-1.5 text-sm md:hidden"
              aria-expanded={menuOpen}
              aria-controls="main-nav"
              onClick={() => setMenuOpen((open) => !open)}
            >
              Menu
            </button>
          </div>
          <nav
            id="main-nav"
            aria-label="Principal"
            className={`${menuOpen ? "block" : "hidden"} border-b border-line px-3 pb-3 md:block md:border-b-0`}
          >
            <ul className="space-y-1">
              {items.map((item) => {
                const active = pathname === item.href;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setMenuOpen(false)}
                      className={`block rounded-lg px-3 py-2 text-sm ${
                        active
                          ? "bg-raised font-medium text-ink"
                          : "text-muted hover:bg-raised/60 hover:text-ink"
                      }`}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center justify-end gap-3 border-b border-line px-4 py-3 sm:px-6">
            <StatusBadge status={live} label={LIVE_LABELS[live]} />
            <div className="min-w-0 text-right text-sm leading-tight">
              <div className="truncate font-medium">{user?.full_name || user?.email}</div>
              <div className="text-xs text-muted">Papel: {user?.role.name}</div>
            </div>
            <button
              onClick={logout}
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-raised"
            >
              Sair
            </button>
          </header>
          <main className="flex-1 px-4 py-6 sm:px-6">{children}</main>
          <footer className="border-t border-line px-4 py-3 text-xs text-muted sm:px-6">
            Resultados simulados ou históricos não garantem resultados futuros. Este sistema não
            constitui recomendação de investimento.
          </footer>
        </div>
      </div>
    </div>
  );
}
