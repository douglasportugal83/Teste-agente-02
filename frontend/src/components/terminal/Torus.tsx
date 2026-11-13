"use client";

import { useCallback, useEffect, useRef } from "react";
import { Canvas, type Draw } from "@/components/terminal/Canvas";
import { C, type Snapshot, normalCdf, num } from "@/lib/terminal";

const RING = 96; // pontos ao redor do anel (tempo do mercado)
const TUBE = 26; // pontos ao redor do tubo (distância à referência)
const MAJOR = 1;
const MINOR = 0.4;
const TILT = 1.12;
export const INPUT_COLORS = [C.warn, C.info, C.ink, C.up, C.down, "#e8d44d"];

type Point = { x: number; y: number; depth: number; scale: number };

/**
 * A "casca" do modelo: um toro em que a volta do anel é o tempo do mercado de 5 min e a volta
 * do tubo é a distância do spot à referência (equador externo = em cima da referência; topo =
 * acima; base = abaixo). A cor de cada ponto é a P(sobe) do modelo naquele lugar. Agulhas
 * brancas marcam por onde o preço passou; agulhas douradas, as compras do robô.
 */
export function Torus({ snapshot, showLinks }: { snapshot: Snapshot; showLinks: boolean }) {
  const dataRef = useRef(snapshot);
  useEffect(() => {
    dataRef.current = snapshot;
  }, [snapshot]);

  const draw = useCallback<Draw>(
    (ctx, w, h, time) => {
      const data = dataRef.current;
      const market = data.market;
      if (!market) return;
      const duration = market.duration;
      const sigma = data.spot.sigma_usd;
      const range = 3 * sigma * Math.sqrt(duration); // distância representada por meia-volta
      const elapsed = Math.min(duration, duration - market.seconds_left);
      const uNow = (elapsed / duration) * Math.PI * 2;
      // O toro gira com o mercado: o "agora" fica sempre voltado para a frente-esquerda.
      const spin = Math.PI * 0.72 - uNow + Math.sin(time / 7000) * 0.12;

      const cx = w * (showLinks ? 0.56 : 0.5);
      const cy = h * 0.52;
      const size = Math.min(w * (showLinks ? 0.25 : 0.3), h * 0.4);
      const cosT = Math.cos(TILT);
      const sinT = Math.sin(TILT);

      const project = (u: number, v: number, lift = 0): Point => {
        const radius = MAJOR + (MINOR + lift) * Math.cos(v);
        const px = radius * Math.cos(u + spin);
        const pz = radius * Math.sin(u + spin);
        const py = (MINOR + lift) * Math.sin(v);
        const y2 = py * sinT - pz * cosT;
        const z2 = py * cosT + pz * sinT;
        const scale = 3.2 / (3.2 + z2);
        return { x: cx + px * size * scale, y: cy - y2 * size * scale, depth: z2, scale };
      };
      const tubeAngle = (d: number) => Math.max(-0.97, Math.min(0.97, d / range)) * Math.PI;

      // --- superfície de probabilidade ---
      for (let i = 0; i < RING; i++) {
        const u = (i / RING) * Math.PI * 2;
        const at = (u / (Math.PI * 2)) * duration;
        const reach = sigma * Math.sqrt(Math.max(duration - at, 0.5));
        const past = at <= elapsed;
        for (let j = 0; j < TUBE; j++) {
          const v = -Math.PI + ((j + 0.5) / TUBE) * Math.PI * 2;
          const p = normalCdf(((v / Math.PI) * range) / reach);
          const certainty = Math.abs(2 * p - 1);
          const point = project(u, v);
          const near = 1 - (point.depth + 1.4) / 2.8; // 1 = perto da câmera
          const alpha = (past ? 0.6 : 0.3) + 0.5 * near * (past ? 1 : 0.6);
          const tone = p >= 0.5 ? [45, 212, 167] : [255, 107, 107];
          const mix = certainty * 0.75;
          const r = Math.round(96 + (tone[0] - 96) * mix);
          const g = Math.round(140 + (tone[1] - 140) * mix);
          const b = Math.round(215 + (tone[2] - 215) * mix);
          ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${Math.max(0.08, Math.min(1, alpha)).toFixed(2)})`;
          const dot = 1.5 + 1.9 * near;
          ctx.fillRect(point.x - dot / 2, point.y - dot / 2, dot, dot);
        }
      }

      const needle = (u: number, v: number, lift: number, color: string, width: number) => {
        const from = project(u, v);
        const to = project(u, v, lift);
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
        return to;
      };

      // --- por onde o preço passou ---
      const path = market.path;
      for (let i = Math.max(0, path.length - 90); i < path.length; i++) {
        const [at, d] = path[i];
        const age = (path.length - 1 - i) / 90;
        needle(
          (at / duration) * Math.PI * 2,
          tubeAngle(d),
          0.05 + 0.12 * (1 - age),
          `rgba(230, 235, 243, ${(0.75 * (1 - age) + 0.08).toFixed(2)})`,
          1,
        );
      }

      // --- compras do robô ---
      for (const fill of market.fills) {
        const u = ((duration - fill.t_left) / duration) * Math.PI * 2;
        const tip = needle(u, tubeAngle(fill.d), 0.14 + 0.09 * Math.log10(fill.usd + 1), C.warn, 1.6);
        ctx.fillStyle = C.warn;
        ctx.beginPath();
        ctx.arc(tip.x, tip.y, 2, 0, 7);
        ctx.fill();
      }
      ctx.lineWidth = 1;

      // --- agora ---
      const dNow = path.length ? path[path.length - 1][1] : 0;
      const here = project(uNow, tubeAngle(dNow), 0.03);
      const pulse = 5 + 2.5 * Math.sin(time / 260);
      ctx.fillStyle = market.leader === "UP" ? C.up : C.down;
      ctx.shadowColor = ctx.fillStyle;
      ctx.shadowBlur = 18;
      ctx.beginPath();
      ctx.arc(here.x, here.y, pulse, 0, 7);
      ctx.fill();
      ctx.shadowBlur = 0;

      ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.textBaseline = "middle";
      ctx.fillStyle = C.ink;
      const label = `SPOT ${dNow >= 0 ? "+" : "−"}$${num(Math.abs(dNow), 1)} · P(SOBE) ${num(market.p_up, 3)}`;
      const labelWidth = ctx.measureText(label).width;
      ctx.fillText(label, Math.min(here.x + 14, w - labelWidth - 4), here.y - 14);

      // --- ligações das entradas do modelo até o ponto atual ---
      if (showLinks) {
        INPUT_COLORS.forEach((color, index) => {
          const startY = ((index + 0.5) / INPUT_COLORS.length) * h;
          const c1x = w * 0.16;
          const c2x = here.x - w * 0.14;
          ctx.strokeStyle = color;
          ctx.globalAlpha = 0.45;
          ctx.beginPath();
          ctx.moveTo(0, startY);
          ctx.bezierCurveTo(c1x, startY, c2x, here.y, here.x, here.y);
          ctx.stroke();
          ctx.globalAlpha = 1;
          // Partícula viajando pela curva (Bézier cúbica avaliada à mão).
          const t = (time / 2400 + index * 0.17) % 1;
          const k = 1 - t;
          const bx = 3 * k * k * t * c1x + 3 * k * t * t * c2x + t * t * t * here.x;
          const by =
            k * k * k * startY + 3 * k * k * t * startY + 3 * k * t * t * here.y + t * t * t * here.y;
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(bx, by, 2.2, 0, 7);
          ctx.fill();
        });
      }
    },
    [showLinks],
  );

  return (
    <Canvas
      draw={draw}
      animate
      label="Superfície de probabilidade do modelo em forma de toro: tempo do mercado ao redor do anel, distância à referência ao redor do tubo, com as compras do robô marcadas"
    />
  );
}
