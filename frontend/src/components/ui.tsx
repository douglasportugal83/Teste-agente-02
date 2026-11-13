import { STATUS_LABELS } from "@/lib/format";

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-panel p-5 ${className}`}>
      {title && (
        <header className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold tracking-wide text-muted uppercase">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

const TONES: Record<string, string> = {
  connected: "bg-accent/15 text-accent",
  running: "bg-accent/15 text-accent",
  online: "bg-accent/15 text-accent",
  paused: "bg-warn/15 text-warn",
  connecting: "bg-warn/15 text-warn",
  not_configured: "bg-muted/15 text-muted",
  disconnected: "bg-danger/15 text-danger",
  offline: "bg-danger/15 text-danger",
  error: "bg-danger/15 text-danger",
  blocked: "bg-danger/15 text-danger",
  stopped: "bg-danger/15 text-danger",
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap ${TONES[status] ?? "bg-muted/15 text-muted"}`}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden />
      {label ?? STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger"
    >
      <span>{message}</span>
      {onRetry && (
        <button onClick={onRetry} className="rounded-md border border-danger/50 px-3 py-1">
          Tentar novamente
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-panel ${className}`} aria-hidden />;
}

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
    </div>
  );
}

/** Tela ainda não implementada: informa o que virá e em qual sprint, sem simular dados. */
export function ComingSoon({
  title,
  sprint,
  features,
}: {
  title: string;
  sprint: number;
  features: string[];
}) {
  return (
    <>
      <PageHeader title={title} subtitle={`Prevista para a Sprint ${sprint} do roteiro.`} />
      <Card title="O que esta tela vai oferecer">
        <ul className="grid gap-2 text-sm sm:grid-cols-2">
          {features.map((feature) => (
            <li key={feature} className="flex gap-2">
              <span className="text-muted" aria-hidden>
                ○
              </span>
              {feature}
            </li>
          ))}
        </ul>
        <p className="mt-5 text-sm text-muted">
          Nada aqui está ativo ainda: a tela não exibe dados fictícios para parecer pronta.
        </p>
      </Card>
    </>
  );
}
