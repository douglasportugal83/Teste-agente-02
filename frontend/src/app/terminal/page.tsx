"use client";

import Link from "next/link";
import { useMemo, useSyncExternalStore } from "react";
import { Canvas } from "@/components/terminal/Canvas";
import { INPUT_COLORS, Torus } from "@/components/terminal/Torus";
import {
  drawCandles,
  drawFeeds,
  drawFunnel,
  drawLateHist,
  drawSpark,
} from "@/components/terminal/charts";
import {
  KIND_LABEL,
  SIDE_LABEL,
  type Side,
  type Snapshot,
  type TerminalStatus,
  cents,
  clock,
  countdown,
  num,
  pct,
  signedUsd,
  usd,
  useTerminal,
} from "@/lib/terminal";

const WIDE = "(min-width: 1024px)";
const subscribeWide = (notify: () => void) => {
  const query = window.matchMedia(WIDE);
  query.addEventListener("change", notify);
  return () => query.removeEventListener("change", notify);
};
const useWide = () =>
  useSyncExternalStore(
    subscribeWide,
    () => window.matchMedia(WIDE).matches,
    () => false,
  );

const sideTone = (side: Side) => (side === "UP" ? "text-accent" : "text-danger");

function Panel({
  title,
  note,
  children,
  className = "",
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-w-0 flex-col rounded-md border border-line bg-panel ${className}`}>
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-3 py-1.5">
        <h2 className="truncate text-[11px] font-semibold tracking-[0.14em] text-ink uppercase">
          <span className="mr-1.5 text-info" aria-hidden>
            ◆
          </span>
          {title}
        </h2>
        {note && <span className="truncate text-[10px] text-muted uppercase">{note}</span>}
      </header>
      <div className="min-h-0 flex-1 p-3">{children}</div>
    </section>
  );
}

function Stat({
  label,
  value,
  tone = "text-ink",
  boxed = false,
}: {
  label: string;
  value: string;
  tone?: string;
  boxed?: boolean;
}) {
  return (
    <div className={boxed ? "rounded border border-line bg-canvas px-2.5 py-1.5" : ""}>
      <div className="text-[10px] tracking-wider text-muted uppercase">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

function Marquee({ items, seconds }: { items: { key: string; node: React.ReactNode }[]; seconds: number }) {
  return (
    <div className="terminal-marquee overflow-hidden whitespace-nowrap">
      <div className="terminal-marquee-track inline-flex" style={{ animationDuration: `${seconds}s` }}>
        {[0, 1].map((copy) => (
          <span key={copy} className="inline-flex" aria-hidden={copy === 1}>
            {items.map((item) => (
              <span key={item.key} className="px-4">
                {item.node}
              </span>
            ))}
          </span>
        ))}
      </div>
    </div>
  );
}

function Book({ snapshot }: { snapshot: Snapshot }) {
  const market = snapshot.market;
  if (!market) return null;
  const { asks, bids, side } = market.book;
  const deepest = Math.max(...asks.map((l) => l[1]), ...bids.map((l) => l[1]), 1);
  const row = ([price, size]: [number, number], ask: boolean) => (
    <div key={`${ask}-${price}`} className="relative grid grid-cols-3 px-1 py-px text-right">
      <div
        className={`absolute inset-y-0 right-0 ${ask ? "bg-danger/25" : "bg-accent/25"}`}
        style={{ width: `${(size / deepest) * 100}%` }}
        aria-hidden
      />
      <span className={`relative text-left ${ask ? "text-danger" : "text-accent"}`}>
        {num(price * 100, 0)}¢
      </span>
      <span className="relative">{num(size, 0)}</span>
      <span className="relative text-muted">{usd(size * price, 0)}</span>
    </div>
  );
  return (
    <div className="font-mono text-[11px] tabular-nums">
      <div className="mb-1 flex justify-between text-[10px] text-muted uppercase">
        <span>
          {market.label} · <span className={sideTone(side)}>{SIDE_LABEL[side]}</span> · T-
          {countdown(market.seconds_left)}
        </span>
        <span>cotas · valor</span>
      </div>
      {[...asks].reverse().map((level) => row(level, true))}
      <div className="my-0.5 flex justify-between border-y border-line px-1 py-0.5 text-[10px] text-muted">
        <span>
          Modelo <span className="text-ink">{num(market.p_leader * 100, 1)}¢</span>
        </span>
        <span>
          Vantagem{" "}
          <span className={market.edge >= 0 ? "text-accent" : "text-danger"}>{cents(market.edge)}</span>
        </span>
      </div>
      {bids.map((level) => row(level, false))}
    </div>
  );
}

const INPUT_SPECS: { label: string; hint: string; column: 0 | 1 | 2 | 3 | 4 | 5; show: (v: number) => string }[] = [
  { label: "Spot − Ref", hint: "distância do preço à referência", column: 0, show: (v) => signedUsd(v) },
  { label: "σ·√t alcance", hint: "quanto o preço ainda pode andar", column: 1, show: (v) => `±${usd(v, 0)}` },
  { label: "Tempo restante", hint: "até a liquidação", column: 2, show: (v) => countdown(v) },
  { label: "P(sobe) modelo", hint: "Φ((spot−ref) / σ√t)", column: 3, show: (v) => num(v, 3) },
  { label: "Oferta do líder", hint: "melhor preço de venda no livro", column: 4, show: (v) => `$${num(v, 2)}` },
  { label: "Vantagem", hint: "P do modelo − oferta", column: 5, show: (v) => cents(v) },
];

function ModelInputs({ snapshot }: { snapshot: Snapshot }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:flex lg:h-full lg:flex-col lg:gap-0">
      {INPUT_SPECS.map((spec, index) => {
        const values = snapshot.inputs.map((row) => row[spec.column]);
        const last = values[values.length - 1];
        return (
          <div key={spec.label} className="flex min-h-0 flex-1 flex-col justify-center lg:pr-2">
            <div
              className="flex items-baseline justify-between gap-2 border-l-2 pl-2"
              style={{ borderColor: INPUT_COLORS[index] }}
            >
              <span className="text-[10px] font-semibold tracking-wider uppercase">{spec.label}</span>
              <span className="font-mono text-xs tabular-nums" style={{ color: INPUT_COLORS[index] }}>
                {last === undefined ? "—" : spec.show(last)}
              </span>
            </div>
            <div className="pl-2 text-[9px] text-muted">{spec.hint}</div>
            <div className="h-6 pl-2">
              <Canvas draw={drawSpark(values, INPUT_COLORS[index])} label={`Histórico de ${spec.label}`} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

const STATUS_TEXT: Record<TerminalStatus, string> = {
  connecting: "Conectando ao motor do terminal…",
  warming: "O motor está aquecendo (simulando a última hora). Só um instante…",
  offline: "Sem conexão com a API. Tentando reconectar…",
  disabled: "O motor do terminal está desligado no backend (TERMINAL_ENGINE_ENABLED=false).",
  live: "",
};

export default function TerminalPage() {
  const { status, snapshot } = useTerminal();
  const wide = useWide();

  const draws = useMemo(() => {
    if (!snapshot) return null;
    return {
      candles: drawCandles(snapshot),
      feeds: drawFeeds(snapshot),
      funnel: snapshot.market ? drawFunnel(snapshot.market, snapshot.spot.sigma_usd) : null,
      hist: drawLateHist(snapshot.late_hist),
    };
  }, [snapshot]);

  const banner = (
    <div className="bg-warn px-4 py-1 text-center text-xs font-semibold text-black">
      MODO SIMULAÇÃO — preço, livro, execuções e lucro são sintéticos; nenhuma ordem real é enviada
    </div>
  );

  if (!snapshot || !snapshot.market || !draws) {
    return (
      <div className="flex min-h-screen flex-col bg-canvas">
        {banner}
        <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center text-sm text-muted">
          <p role="status">{STATUS_TEXT[status] || "Carregando…"}</p>
          <Link href="/dashboard" className="rounded-md border border-line px-3 py-1.5 text-ink hover:bg-raised">
            Voltar ao painel
          </Link>
        </div>
      </div>
    );
  }

  const { market, stats, spot } = snapshot;
  const pnlTone = stats.realized_pnl >= 0 ? "text-accent" : "text-danger";
  const sessionHours = stats.session_seconds / 3600;

  return (
    <div className="flex min-h-screen flex-col bg-canvas font-mono text-ink">
      {banner}

      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-line px-3 py-2">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/dashboard"
            className="grid size-9 shrink-0 place-items-center rounded-md bg-info/20 text-sm font-bold text-info hover:bg-info/30"
            title="Voltar ao painel"
            aria-label="Voltar ao painel"
          >
            TA
          </Link>
          <div className="min-w-0">
            <div className="truncate text-[10px] tracking-wider text-muted uppercase">
              ◆ {snapshot.strategy.name}
            </div>
            <div className="truncate text-sm font-bold tracking-[0.12em] uppercase">
              <span className="text-info">TraderAI</span> {"//"} Robô de mercados binários
            </div>
            <div className="truncate text-[10px] text-muted uppercase">
              BTC sobe/desce · 5m + 15m · observa {snapshot.strategy.watch_seconds / 60} min · compra o
              líder abaixo da P do modelo
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
          <Stat label="BTC spot" value={usd(spot.price)} />
          <Stat
            label="1ª entrada (mediana)"
            value={stats.first_entry_median_s === null ? "—" : `T-${num(stats.first_entry_median_s, 0)}s`}
          />
          <Stat label="Compras ≥ $0,80" value={pct(stats.share_buys_ge_80)} />
          <Stat label="Vantagem média" value={cents(stats.avg_edge)} tone="text-accent" />
          <div className="text-right">
            <div className="text-base font-bold tabular-nums">{clock(snapshot.ts)} UTC</div>
            <div className="flex items-center justify-end gap-1.5 text-[10px] text-warn uppercase">
              <span className={`size-1.5 rounded-full ${status === "live" ? "bg-accent" : "bg-danger"}`} aria-hidden />
              {status === "live" ? "Simulação ao vivo" : STATUS_TEXT[status]}
            </div>
          </div>
        </div>
      </header>

      <div className="flex items-center border-b border-line text-[11px] uppercase">
        <span className="shrink-0 bg-danger px-3 py-1 font-bold text-black">● Eventos</span>
        <Marquee
          seconds={70}
          items={
            snapshot.events.length
              ? snapshot.events.map((event) => ({
                  key: `${event.ts}-${event.text}`,
                  node: (
                    <>
                      <span className="mr-2 font-bold">{KIND_LABEL[event.kind as keyof typeof KIND_LABEL] ?? "LIQUIDADO"}</span>
                      <span className={event.tone === "up" ? "text-accent" : event.tone === "down" ? "text-danger" : "text-muted"}>
                        {event.text}
                      </span>
                    </>
                  ),
                }))
              : [{ key: "empty", node: <span className="text-muted">Aguardando o primeiro evento…</span> }]
          }
        />
      </div>

      <main className="grid flex-1 grid-cols-1 gap-2 p-2 lg:grid-cols-12">
        <Panel title="Carteira simulada" note="capital fictício" className="lg:col-span-3">
          <div className="text-[10px] tracking-wider text-muted uppercase">
            Resultado da sessão · {num(sessionHours, 1)} h
          </div>
          <div className={`text-4xl font-bold tabular-nums ${pnlTone}`}>{signedUsd(stats.realized_pnl)}</div>
          <div className="mt-1 text-[11px] text-muted">
            méd. {stats.avg_usd === null ? "—" : usd(stats.avg_usd)} · med.{" "}
            {stats.median_usd === null ? "—" : usd(stats.median_usd)} · {signedUsd(stats.pnl_per_hour)}/h
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <Stat label="Compras 24h" value={num(stats.trades_24h, 0)} />
            <Stat label="Acerto" value={pct(stats.win_rate)} tone="text-accent" />
            <Stat label="Mercados" value={num(stats.markets_traded, 0)} />
            <Stat label="Em aberto" value={usd(stats.open_stake)} />
            <Stat label="Risco de virada" value={`${num(market.flip_risk, 1)}/10`} tone={market.flip_risk > 4 ? "text-danger" : "text-warn"} />
            <Stat
              label="Estado"
              value={{ idle: "OCIOSO", watching: "OBSERVANDO", trading: "POSICIONADO" }[market.state]}
              tone={market.state === "idle" ? "text-muted" : "text-warn"}
            />
          </div>
          <div className="mt-3 border-t border-line pt-2">
            <div className="mb-1 flex justify-between text-[10px] text-muted uppercase">
              <span>Compras por tempo até o fim</span>
              <span>{pct(stats.share_buys_last_minute)} no último minuto</span>
            </div>
            <div className="h-14">
              <Canvas draw={draws.hist} label="Dólares comprados por faixa de 10 segundos até o vencimento" />
            </div>
            <div className="flex justify-between text-[9px] text-muted">
              <span>T-240s</span>
              <span>liquidação</span>
            </div>
          </div>
        </Panel>

        <Panel
          title="BTC spot"
          note={`1m · ${spot.change_pct >= 0 ? "▲" : "▼"} ${num(Math.abs(spot.change_pct), 2)}%`}
          className="lg:col-span-3"
        >
          <div className="h-40">
            <Canvas draw={draws.candles} label="Candles de 1 minuto do BTC com a referência do mercado atual" />
          </div>
          <div className="mt-2">
            <Book snapshot={snapshot} />
          </div>
        </Panel>

        <div className="grid min-w-0 gap-2 lg:col-span-6">
          <Panel title="Latência e base dos feeds" note="spot · perp · oráculo">
            <div className="grid gap-3 sm:grid-cols-[1fr_9rem]">
              <div>
                <div className="mb-1 flex flex-wrap gap-x-4 text-[10px] uppercase">
                  <span className="text-ink">━ Spot (modelo)</span>
                  <span className="text-[#a78bfa]">━ Perp</span>
                  <span className="text-warn">━ Oráculo (liquida)</span>
                </div>
                <div className="h-32">
                  <Canvas draw={draws.feeds} label="Preços do spot, do perpétuo e do oráculo nos últimos dois minutos" />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-1">
                <Stat label="Idade do oráculo" value={`${num(spot.oracle_age_ms, 0)} ms`} tone="text-warn" />
                <Stat label="Spot − oráculo" value={`${num(spot.spot_oracle_bp, 2)} bp`} tone="text-info" />
                <Stat label="Oráculo vs ref" value={signedUsd(spot.oracle - market.reference)} tone={spot.oracle >= market.reference ? "text-accent" : "text-danger"} />
                <Stat label="P modelo · líder" value={`${num(market.p_leader, 3)} ${SIDE_LABEL[market.leader]}`} tone={sideTone(market.leader)} />
              </div>
            </div>
          </Panel>

          <Panel title="Inspetor de mensagens" note="feed sintético">
            <div className="grid gap-3 sm:grid-cols-[1fr_9rem]">
              <ol className="h-36 overflow-hidden text-[10px] leading-[1.35] text-muted">
                {[...snapshot.wire].reverse().map((message) => (
                  <li key={message.seq} className="truncate">
                    <span className="text-ink/70">{clock(message.ts)}</span>{" "}
                    <span className="text-info">{message.ch}</span>{" "}
                    <span className={message.type === "fill" ? "font-bold text-warn" : "text-ink"}>{message.type}</span>{" "}
                    {`{${message.body}}`}
                  </li>
                ))}
              </ol>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-1">
                <Stat label="Mensagens / s" value={num(snapshot.wire_stats.msgs_per_s, 1)} tone="text-info" />
                <Stat label="Execuções na sessão" value={num(stats.fills_total, 0)} />
                <Stat label="Bytes na sessão" value={`${num(snapshot.wire_stats.bytes / 1024, 1)} KB`} />
                <Stat label="Última sequência" value={`#${snapshot.wire_stats.seq}`} tone="text-warn" />
              </div>
            </div>
          </Panel>
        </div>

        <Panel
          title="Casca do modelo"
          note={`superfície P(sobe) · ${market.label} · anel = tempo · tubo = spot − ref`}
          className="lg:col-span-12"
        >
          <div className="grid gap-3 lg:h-[30rem] lg:grid-cols-[12rem_1fr_13rem] lg:grid-rows-[minmax(0,1fr)]">
            <ModelInputs snapshot={snapshot} />
            <div className="relative h-80 min-w-0 lg:h-full">
              <Torus snapshot={snapshot} showLinks={wide} />
              <div className="pointer-events-none absolute top-0 right-0 left-0 text-center text-[10px] text-info uppercase">
                P({SIDE_LABEL[market.leader]}) {num(market.p_leader, 3)} · oferta {num(market.ask_leader, 2)} · vantagem{" "}
                {cents(market.edge)}
              </div>
              <div className="pointer-events-none absolute right-0 bottom-0 left-0 text-[10px] text-muted">
                Agulha branca = por onde o preço passou · agulha dourada = compra do robô · verde/vermelho =
                modelo certo de sobe/desce
              </div>
            </div>
            <div className="flex min-h-0 flex-col">
              <div className="mb-1 flex justify-between text-[10px] text-muted uppercase">
                <span>Últimas compras</span>
                <span>valor</span>
              </div>
              <ol className="flex-1 space-y-1 overflow-hidden">
                {snapshot.tape.slice(0, wide ? 9 : 4).map((fill) => (
                  <li key={fill.seq} className="rounded border border-line bg-canvas px-2 py-1">
                    <div className="flex justify-between text-[11px] font-semibold">
                      <span className={sideTone(fill.side)}>
                        {KIND_LABEL[fill.kind]} {SIDE_LABEL[fill.side]}
                      </span>
                      <span className="text-warn tabular-nums">{usd(fill.usd)}</span>
                    </div>
                    <div className="flex justify-between text-[9px] text-muted">
                      <span>
                        @ {num(fill.price, 2)} · T-{num(fill.t_left, 0)}s
                      </span>
                      <span>{fill.market}</span>
                    </div>
                  </li>
                ))}
                {snapshot.tape.length === 0 && <li className="text-[11px] text-muted">Nenhuma compra ainda.</li>}
              </ol>
            </div>
          </div>
        </Panel>

        <Panel title="Fita de execuções" note="entradas, reforços, proteções e viradas" className="lg:col-span-6">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-right text-[11px] tabular-nums">
              <thead className="text-[10px] text-muted uppercase">
                <tr>
                  <th className="text-left font-normal">Hora</th>
                  <th className="text-left font-normal">Mercado</th>
                  <th className="text-left font-normal">Lado</th>
                  <th className="text-left font-normal">Tipo</th>
                  <th className="font-normal">Preço</th>
                  <th className="font-normal">Valor</th>
                  <th className="font-normal">P mod.</th>
                  <th className="font-normal">Vant.</th>
                  <th className="font-normal">T-</th>
                  <th className="font-normal">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {snapshot.tape.slice(0, 14).map((fill) => (
                  <tr key={fill.seq} className="border-t border-line/50">
                    <td className="text-left text-muted">{clock(fill.ts)}</td>
                    <td className="text-left">{fill.market}</td>
                    <td className={`text-left ${sideTone(fill.side)}`}>{SIDE_LABEL[fill.side]}</td>
                    <td className="text-left text-info">{KIND_LABEL[fill.kind]}</td>
                    <td>{num(fill.price, 2)}</td>
                    <td>{usd(fill.usd)}</td>
                    <td>{num(fill.p_model, 3)}</td>
                    <td className="text-accent">{cents(fill.edge)}</td>
                    <td className="text-muted">{num(fill.t_left, 0)}s</td>
                    <td className={fill.pnl === null ? "text-muted" : fill.pnl >= 0 ? "text-accent" : "text-danger"}>
                      {fill.pnl === null ? "aberta" : signedUsd(fill.pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {snapshot.tape.length === 0 && <p className="py-4 text-center text-[11px] text-muted">Nenhuma execução ainda.</p>}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat boxed label="Última compra" value={snapshot.tape[0] ? `${usd(snapshot.tape[0].usd)} ${SIDE_LABEL[snapshot.tape[0].side]} @ ${num(snapshot.tape[0].price, 2)}` : "—"} tone={snapshot.tape[0] ? sideTone(snapshot.tape[0].side) : "text-muted"} />
            <Stat boxed label="Média / mediana" value={stats.avg_usd === null || stats.median_usd === null ? "—" : `${usd(stats.avg_usd)} / ${usd(stats.median_usd)}`} />
            <Stat boxed label="Compras ≥ $0,80" value={pct(stats.share_buys_ge_80)} tone="text-info" />
            <Stat boxed label="Acerto · liquidados" value={pct(stats.win_rate)} tone="text-warn" />
          </div>
        </Panel>

        <Panel title="Funil de resolução" note="faixa de σ·√t até a liquidação" className="lg:col-span-6">
          <div className="h-56">
            {draws.funnel && (
              <Canvas draw={draws.funnel} label="Trajetória do preço em relação à referência, dentro do funil de um e dois desvios-padrão que se fecha até a liquidação" />
            )}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat boxed label="Até a liquidação" value={countdown(market.seconds_left)} tone="text-info" />
            <Stat boxed label="Cone σ·√t" value={`±${usd(market.reach_usd, 0)}`} tone="text-info" />
            <Stat boxed label="P justa de subir" value={pct(market.p_up)} tone={market.p_up >= 0.5 ? "text-accent" : "text-danger"} />
            <Stat boxed label="Posição líquida" value={market.position.stake > 0 ? `${num(market.position.net_shares, 0)} cotas ${SIDE_LABEL[market.position.net_side]}` : "sem posição"} tone={market.position.stake > 0 ? sideTone(market.position.net_side) : "text-muted"} />
          </div>
        </Panel>
      </main>

      <footer className="border-t border-line text-[10px] text-muted uppercase">
        <Marquee
          seconds={90}
          items={[
            ...snapshot.markets.map((m) => ({
              key: m.label,
              node: (
                <>
                  {m.label} · T-{countdown(m.seconds_left)} · P(sobe) {num(m.p_up, 3)} · investido {usd(m.stake)}
                </>
              ),
            })),
            ...snapshot.settled.slice(0, 6).map((s) => ({
              key: s.id,
              node: (
                <>
                  {s.label} {clock(s.end)} · {SIDE_LABEL[s.outcome]} ·{" "}
                  <span className={s.pnl >= 0 ? "text-accent" : "text-danger"}>{signedUsd(s.pnl)}</span>
                </>
              ),
            })),
            {
              key: "premise",
              node: (
                <>
                  Premissa do mundo sintético: o livro segue o modelo com {num(snapshot.strategy.book_lag_seconds, 1)} s de
                  atraso — é daí que vem a vantagem. Resultados simulados não garantem resultados futuros.
                </>
              ),
            },
          ]}
        />
      </footer>
    </div>
  );
}
