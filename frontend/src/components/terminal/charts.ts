import type { Draw } from "@/components/terminal/Canvas";
import { C, type MarketView, type Snapshot, num } from "@/lib/terminal";

const FONT = "10px ui-monospace, SFMono-Regular, Menlo, monospace";

function grid(ctx: CanvasRenderingContext2D, w: number, h: number, rows: number, right = 0) {
  ctx.strokeStyle = C.line;
  ctx.lineWidth = 1;
  ctx.setLineDash([2, 4]);
  ctx.beginPath();
  for (let i = 1; i < rows; i++) {
    const y = Math.round((h * i) / rows) + 0.5;
    ctx.moveTo(0, y);
    ctx.lineTo(w - right, y);
  }
  ctx.stroke();
  ctx.setLineDash([]);
}

/** Candles de 1 minuto do spot, com a referência do mercado atual e o último preço. */
export function drawCandles(snapshot: Snapshot): Draw {
  const candles = snapshot.candles.slice(-48);
  const reference = snapshot.market?.reference ?? null;
  return (ctx, w, h) => {
    if (candles.length === 0) return;
    const axis = 52;
    const plot = w - axis;
    let low = Math.min(...candles.map((c) => c[3]));
    let high = Math.max(...candles.map((c) => c[2]));
    if (reference !== null) {
      low = Math.min(low, reference);
      high = Math.max(high, reference);
    }
    const pad = (high - low) * 0.08 || 1;
    low -= pad;
    high += pad;
    const y = (price: number) => h - ((price - low) / (high - low)) * h;
    const step = plot / candles.length;
    const body = Math.max(2, step * 0.62);

    grid(ctx, w, h, 4, axis);
    for (const [index, [, open, top, bottom, close]] of candles.entries()) {
      const x = index * step + step / 2;
      const color = close >= open ? C.up : C.down;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(Math.round(x) + 0.5, y(top));
      ctx.lineTo(Math.round(x) + 0.5, y(bottom));
      ctx.stroke();
      const yTop = y(Math.max(open, close));
      ctx.fillRect(x - body / 2, yTop, body, Math.max(1, y(Math.min(open, close)) - yTop));
    }

    ctx.font = FONT;
    ctx.textBaseline = "middle";
    const tag = (price: number, color: string, text: string, dashed: boolean) => {
      const py = Math.round(y(price)) + 0.5;
      ctx.strokeStyle = color;
      ctx.setLineDash(dashed ? [4, 4] : []);
      ctx.beginPath();
      ctx.moveTo(0, py);
      ctx.lineTo(plot, py);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = color;
      ctx.fillRect(plot, py - 8, axis, 16);
      ctx.fillStyle = C.bg;
      ctx.fillText(text, plot + 4, py);
    };
    if (reference !== null) tag(reference, C.warn, `REF ${num(reference, 0)}`, true);
    const last = candles[candles.length - 1][4];
    tag(last, last >= candles[candles.length - 1][1] ? C.up : C.down, num(last, 0), false);
  };
}

/** Últimos ~2 min dos três feeds: spot (linha), perp (linha) e oráculo (degraus). */
export function drawFeeds(snapshot: Snapshot): Draw {
  const rows = snapshot.feeds;
  return (ctx, w, h) => {
    if (rows.length < 2) return;
    const values = rows.flatMap((r) => [r[1], r[2], r[3]]);
    let low = Math.min(...values);
    let high = Math.max(...values);
    const pad = (high - low) * 0.1 || 1;
    low -= pad;
    high += pad;
    const t0 = rows[0][0];
    const span = rows[rows.length - 1][0] - t0 || 1;
    const x = (t: number) => ((t - t0) / span) * w;
    const y = (price: number) => h - ((price - low) / (high - low)) * h;

    grid(ctx, w, h, 4);
    // Área entre spot e oráculo: o quanto o oráculo está "atrasado" a cada instante.
    ctx.fillStyle = "rgba(245, 185, 66, 0.12)";
    ctx.beginPath();
    rows.forEach((r, i) => (i ? ctx.lineTo(x(r[0]), y(r[1])) : ctx.moveTo(x(r[0]), y(r[1]))));
    for (let i = rows.length - 1; i >= 0; i--) {
      ctx.lineTo(x(rows[i][0]), y(rows[i][3]));
      if (i > 0) ctx.lineTo(x(rows[i][0]), y(rows[i - 1][3]));
    }
    ctx.fill();

    const line = (column: 1 | 2 | 3, color: string, width: number, stepped: boolean) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      rows.forEach((r, i) => {
        if (i === 0) ctx.moveTo(x(r[0]), y(r[column]));
        else {
          if (stepped) ctx.lineTo(x(r[0]), y(rows[i - 1][column]));
          ctx.lineTo(x(r[0]), y(r[column]));
        }
      });
      ctx.stroke();
      ctx.lineWidth = 1;
    };
    line(2, C.perp, 1, false);
    line(3, C.warn, 1.5, true);
    line(1, C.ink, 1.5, false);

    ctx.font = FONT;
    ctx.fillStyle = C.muted;
    ctx.textBaseline = "bottom";
    ctx.fillText(`−${Math.round(span)}s`, 2, h - 2);
    ctx.textAlign = "right";
    ctx.fillText("agora", w - 2, h - 2);
    ctx.textBaseline = "top";
    ctx.fillText(num(high, 0), w - 2, 2);
    ctx.textAlign = "left";
  };
}

/**
 * Funil de resolução: faixa de ±1σ·√t e ±2σ·√t em torno da referência, que se fecha até a
 * liquidação. Enquanto o preço anda fora da faixa de 1σ, a P do modelo para o líder é ≥ 84%.
 */
export function drawFunnel(market: MarketView, sigmaUsd: number): Draw {
  return (ctx, w, h) => {
    const duration = market.duration;
    const left = 6;
    const right = w - 74;
    const mid = h / 2;
    const reachAtOpen = sigmaUsd * Math.sqrt(duration);
    const extreme = Math.max(
      2.2 * reachAtOpen,
      ...market.path.map((p) => Math.abs(p[1]) * 1.15),
      1,
    );
    const x = (elapsed: number) => left + (elapsed / duration) * (right - left);
    const y = (d: number) => mid - (d / extreme) * (mid - 6);

    const band = (k: number, fill: string) => {
      ctx.fillStyle = fill;
      ctx.beginPath();
      for (let i = 0; i <= 60; i++) {
        const e = (duration * i) / 60;
        ctx.lineTo(x(e), y(k * sigmaUsd * Math.sqrt(duration - e)));
      }
      for (let i = 60; i >= 0; i--) {
        const e = (duration * i) / 60;
        ctx.lineTo(x(e), y(-k * sigmaUsd * Math.sqrt(duration - e)));
      }
      ctx.fill();
    };
    band(2, "rgba(90, 169, 255, 0.07)");
    band(1, "rgba(90, 169, 255, 0.13)");

    // Janela em que o robô pode comprar.
    const watchStart = x(Math.max(0, duration - 240));
    ctx.strokeStyle = "rgba(245, 185, 66, 0.35)";
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.moveTo(watchStart, 4);
    ctx.lineTo(watchStart, h - 4);
    ctx.stroke();

    ctx.strokeStyle = C.muted;
    ctx.beginPath();
    ctx.moveTo(left, Math.round(mid) + 0.5);
    ctx.lineTo(right, Math.round(mid) + 0.5);
    ctx.stroke();
    ctx.setLineDash([]);

    // Trajetória: verde acima da referência, vermelha abaixo.
    ctx.lineWidth = 2;
    for (let i = 1; i < market.path.length; i++) {
      const [e0, d0] = market.path[i - 1];
      const [e1, d1] = market.path[i];
      ctx.strokeStyle = d1 >= 0 ? C.up : C.down;
      ctx.beginPath();
      ctx.moveTo(x(e0), y(d0));
      ctx.lineTo(x(e1), y(d1));
      ctx.stroke();
    }
    ctx.lineWidth = 1;

    for (const fill of market.fills) {
      ctx.fillStyle = C.warn;
      ctx.beginPath();
      ctx.arc(x(duration - fill.t_left), y(fill.d), Math.min(6, 2 + Math.log10(fill.usd + 1) * 1.6), 0, 7);
      ctx.fill();
    }

    const now = market.path[market.path.length - 1];
    if (now) {
      const reach = sigmaUsd * Math.sqrt(Math.max(0, duration - now[0]));
      ctx.strokeStyle = C.ink;
      ctx.beginPath();
      ctx.ellipse(x(now[0]), mid, 7, Math.max(4, (reach / extreme) * (mid - 6)), 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = C.ink;
      ctx.shadowColor = C.ink;
      ctx.shadowBlur = 12;
      ctx.beginPath();
      ctx.arc(x(now[0]), y(now[1]), 3.5, 0, 7);
      ctx.fill();
      ctx.shadowBlur = 0;
    }

    ctx.font = FONT;
    ctx.textBaseline = "middle";
    ctx.fillStyle = C.up;
    ctx.fillText("▲ SOBE", right + 8, mid - 16);
    ctx.fillStyle = C.warn;
    ctx.fillText("LIQUIDAÇÃO", right + 8, mid);
    ctx.fillStyle = C.down;
    ctx.fillText("▼ DESCE", right + 8, mid + 16);
    ctx.fillStyle = C.muted;
    ctx.textBaseline = "top";
    ctx.fillText(`±1σ√t · ±2σ√t   topo = +$${num(extreme, 0)}`, left, 2);
    ctx.fillText("janela de compra →", Math.min(watchStart + 4, right - 110), h - 14);
  };
}

export function drawSpark(values: number[], color: string): Draw {
  return (ctx, w, h) => {
    if (values.length < 2) return;
    const low = Math.min(...values);
    const span = Math.max(...values) - low || 1;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    values.forEach((value, i) => {
      const px = (i / (values.length - 1)) * w;
      const py = h - 2 - ((value - low) / span) * (h - 4);
      if (i) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
    });
    ctx.stroke();
    ctx.lineWidth = 1;
  };
}

/** Dólares comprados por faixa de 10 s até o vencimento (direita = último instante). */
export function drawLateHist(hist: number[]): Draw {
  return (ctx, w, h) => {
    const max = Math.max(...hist, 1);
    const bar = w / hist.length;
    hist.forEach((value, bucket) => {
      const height = (value / max) * (h - 2);
      ctx.fillStyle = bucket < 6 ? C.warn : "rgba(245, 185, 66, 0.4)";
      ctx.fillRect(w - (bucket + 1) * bar + 1, h - height, Math.max(1, bar - 2), height);
    });
  };
}
