"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { Candle } from "@/lib/api";

const UP = "#2dd4a7";
const DOWN = "#ff6b6b";

type Props = {
  /** Muda quando a série exibida é outra (símbolo/timeframe): recria o enquadramento. */
  seriesKey: string;
  candles: Candle[];
  digits: number;
};

export function CandleChart({ seriesKey, candles, digits }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const price = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null);
  const shownKey = useRef<string | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const instance = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8a97ad",
        fontFamily: "inherit",
      },
      grid: { vertLines: { color: "#1a2233" }, horzLines: { color: "#1a2233" } },
      rightPriceScale: { borderColor: "#232d40" },
      timeScale: { borderColor: "#232d40", timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    price.current = instance.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      borderVisible: false,
    });
    volume.current = instance.addSeries(HistogramSeries, {
      priceScaleId: "volume",
      priceFormat: { type: "volume" },
      lastValueVisible: false,
      priceLineVisible: false,
    });
    // Volume ocupa o quinto inferior, sem sobrepor os candles.
    instance.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    instance.priceScale("right").applyOptions({ scaleMargins: { top: 0.06, bottom: 0.22 } });
    chart.current = instance;
    return () => {
      instance.remove();
      chart.current = price.current = volume.current = null;
      shownKey.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !price.current || !volume.current) return;
    price.current.applyOptions({
      priceFormat: { type: "price", precision: digits, minMove: 1 / 10 ** digits },
    });
    price.current.setData(
      candles.map((c) => ({
        time: c.t as UTCTimestamp,
        open: c.o,
        high: c.h,
        low: c.l,
        close: c.c,
      })),
    );
    volume.current.setData(
      candles.map((c) => ({
        time: c.t as UTCTimestamp,
        value: c.v,
        color: c.c >= c.o ? "rgba(45, 212, 167, 0.35)" : "rgba(255, 107, 107, 0.35)",
      })),
    );
    // Só reenquadra ao trocar de série; atualizações preservam o zoom do usuário.
    if (shownKey.current !== seriesKey) {
      shownKey.current = seriesKey;
      const total = candles.length;
      chart.current.timeScale().setVisibleLogicalRange({ from: Math.max(0, total - 160), to: total + 4 });
    }
  }, [seriesKey, candles, digits]);

  return (
    <div
      ref={container}
      className="h-[26rem] w-full"
      role="img"
      aria-label="Gráfico de candles com volume"
    />
  );
}
