"use client";

import { useEffect, useState } from "react";
import { API_URL, getToken } from "@/lib/api";

export type Side = "UP" | "DOWN";

export type TapeFill = {
  seq: number;
  ts: number;
  market: string;
  side: Side;
  kind: "ENTRY" | "ADD" | "HEDGE" | "FLIP";
  price: number;
  usd: number;
  shares: number;
  p_model: number;
  edge: number;
  t_left: number;
  d: number;
  pnl: number | null;
};

export type MarketView = {
  id: string;
  label: string;
  duration: number;
  start: number;
  end: number;
  seconds_left: number;
  reference: number;
  p_up: number;
  implied_up: number;
  leader: Side;
  p_leader: number;
  ask_leader: number;
  edge: number;
  state: "idle" | "watching" | "trading";
  flip_risk: number;
  flips_late: number;
  reach_usd: number;
  book: { side: Side; asks: [number, number][]; bids: [number, number][] };
  position: {
    up_shares: number;
    down_shares: number;
    stake: number;
    net_side: Side;
    net_shares: number;
  };
  first_entry_left: number | null;
  /** [segundos desde a abertura, spot − referência, P(sobe)] */
  path: [number, number, number][];
  fills: { t_left: number; d: number; usd: number; side: Side }[];
};

export type Snapshot = {
  ts: number;
  simulated: true;
  strategy: {
    name: string;
    watch_seconds: number;
    min_leader_p: number;
    min_edge: number;
    max_ask: number;
    max_stake_per_market: number;
    book_lag_seconds: number;
  };
  spot: {
    price: number;
    perp: number;
    oracle: number;
    change_pct: number;
    oracle_age_ms: number;
    spot_oracle_bp: number;
    basis_bp: number;
    sigma_usd: number;
  };
  /** [minuto (epoch s), abertura, máxima, mínima, fechamento] */
  candles: [number, number, number, number, number][];
  /** [epoch s, spot, perp, oráculo] */
  feeds: [number, number, number, number][];
  market: MarketView | null;
  markets: { label: string; seconds_left: number; p_up: number; leader: Side; stake: number }[];
  stats: {
    realized_pnl: number;
    fills_total: number;
    markets_traded: number;
    win_rate: number | null;
    avg_usd: number | null;
    median_usd: number | null;
    first_entry_median_s: number | null;
    share_buys_ge_80: number | null;
    share_buys_last_minute: number | null;
    avg_edge: number | null;
    trades_24h: number;
    pnl_per_hour: number;
    open_stake: number;
    session_seconds: number;
  };
  /** [spot − ref, alcance σ√t, segundos restantes, P(sobe), oferta do líder, vantagem] */
  inputs: [number, number, number, number, number, number][];
  late_hist: number[];
  tape: TapeFill[];
  settled: {
    id: string;
    label: string;
    end: number;
    outcome: Side;
    stake: number;
    pnl: number;
    fills: number;
  }[];
  wire: { seq: number; ts: number; ch: string; type: string; body: string }[];
  wire_stats: { msgs_per_s: number; seq: number; bytes: number };
  events: { ts: number; kind: string; text: string; tone: "info" | "up" | "down" }[];
};

export type TerminalStatus = "connecting" | "warming" | "live" | "offline" | "disabled";

/** Assina /ws/terminal, reconectando com backoff exponencial. */
export function useTerminal(): { status: TerminalStatus; snapshot: Snapshot | null } {
  const [status, setStatus] = useState<TerminalStatus>("connecting");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false;
    let disabled = false;

    const connect = () => {
      const token = getToken();
      if (closed || !token) return;
      socket = new WebSocket(`${API_URL.replace(/^http/, "ws")}/ws/terminal`);
      // O token vai na primeira mensagem, não na URL, para não aparecer em logs.
      socket.onopen = () => socket?.send(JSON.stringify({ type: "auth", token }));
      socket.onmessage = (event) => {
        attempt = 0;
        const message = JSON.parse(event.data as string) as
          | { type: "snapshot"; data: Snapshot }
          | { type: "warming" | "disabled" };
        if (message.type === "snapshot") {
          setSnapshot(message.data);
          setStatus("live");
        } else if (message.type === "disabled") {
          disabled = true;
          setStatus("disabled");
        } else {
          setStatus("warming");
        }
      };
      socket.onclose = () => {
        if (closed || disabled) return;
        setStatus("offline");
        timer = setTimeout(connect, Math.min(30_000, 1_000 * 2 ** attempt++));
      };
    };
    connect();

    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { status, snapshot };
}

const formatter = (digits: number) =>
  new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const FORMATTERS = [formatter(0), formatter(1), formatter(2), formatter(3)];

export const num = (value: number, digits: 0 | 1 | 2 | 3 = 2) => FORMATTERS[digits].format(value);
export const usd = (value: number, digits: 0 | 2 = 2) => `$${num(Math.abs(value), digits)}`;
export const signedUsd = (value: number, digits: 0 | 2 = 2) =>
  `${value >= 0 ? "+" : "−"}${usd(value, digits)}`;
export const pct = (value: number | null, digits: 0 | 1 = 1) =>
  value === null ? "—" : `${num(value * 100, digits)}%`;
export const cents = (value: number | null) =>
  value === null ? "—" : `${value >= 0 ? "+" : "−"}${num(Math.abs(value) * 100, 2)}¢`;
export const clock = (epochSeconds: number) =>
  new Date(epochSeconds * 1000).toISOString().slice(11, 19);
export const countdown = (seconds: number) => {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export const SIDE_LABEL: Record<Side, string> = { UP: "SOBE", DOWN: "DESCE" };
export const KIND_LABEL: Record<TapeFill["kind"], string> = {
  ENTRY: "ENTRADA",
  ADD: "REFORÇO",
  HEDGE: "PROTEÇÃO",
  FLIP: "VIRADA",
};

/** Paleta dos gráficos em canvas (espelha os tokens de globals.css). */
export const C = {
  bg: "#0a0e15",
  panel: "#111723",
  line: "#232d40",
  ink: "#e6ebf3",
  muted: "#8a97ad",
  up: "#2dd4a7",
  down: "#ff6b6b",
  info: "#5aa9ff",
  warn: "#f5b942",
  perp: "#a78bfa",
};

/** Φ(x) — mesma função do modelo no backend, para desenhar a superfície de probabilidade. */
export function normalCdf(x: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const tail =
    0.3989423 *
    Math.exp((-x * x) / 2) *
    t *
    (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x >= 0 ? 1 - tail : tail;
}
