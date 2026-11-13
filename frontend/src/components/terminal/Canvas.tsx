"use client";

import { useEffect, useRef } from "react";

export type Draw = (
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  timeMs: number,
) => void;

/**
 * Canvas responsivo com correção de densidade de pixels.
 * Sem `animate`, redesenha quando `draw` muda; com `animate`, a cada quadro.
 */
export function Canvas({
  draw,
  animate = false,
  label,
  className = "",
}: {
  draw: Draw;
  animate?: boolean;
  label: string;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawRef = useRef(draw);
  const paintRef = useRef<() => void>(() => {});

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let frame = 0;
    let width = 0;
    let height = 0;

    const paint = (time: number) => {
      if (width === 0 || height === 0) return;
      ctx.clearRect(0, 0, width, height);
      drawRef.current(ctx, width, height, time);
    };
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      paint(performance.now());
    };
    paintRef.current = () => paint(performance.now());

    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (animate && !still) {
      const loop = (time: number) => {
        paint(time);
        frame = requestAnimationFrame(loop);
      };
      frame = requestAnimationFrame(loop);
    }
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [animate]);

  useEffect(() => {
    drawRef.current = draw;
    paintRef.current();
  }, [draw]);

  // O canvas fica fora do fluxo: assim o tamanho do bitmap nunca empurra o layout do pai.
  return (
    <div className={`relative h-full w-full ${className}`}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={label}
        className="absolute inset-0 block h-full w-full"
      />
    </div>
  );
}
