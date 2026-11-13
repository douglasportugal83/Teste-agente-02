import { money } from "@/lib/format";

type Point = { ts: string; equity: number };

/** Curva de patrimônio fictício em SVG. (Lightweight Charts entra na Sprint 7.) */
export function EquityChart({ points, currency }: { points: Point[]; currency: string }) {
  if (points.length < 2) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-line px-4 text-center text-sm text-muted">
        A curva aparecerá quando houver operações simuladas encerradas.
      </div>
    );
  }
  const width = 600;
  const height = 160;
  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * width;
      const y = height - 8 - ((p.equity - min) / span) * (height - 16);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = values[values.length - 1];
  const positive = last >= values[0];

  return (
    <figure>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="h-40 w-full"
        preserveAspectRatio="none"
        role="img"
        aria-label={`Patrimônio fictício de ${money(values[0], currency)} a ${money(last, currency)}`}
      >
        <path
          d={path}
          fill="none"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
          className={positive ? "stroke-accent" : "stroke-danger"}
        />
      </svg>
      <figcaption className="mt-2 flex justify-between text-xs text-muted">
        <span>Mín. {money(min, currency)}</span>
        <span>Máx. {money(max, currency)}</span>
      </figcaption>
    </figure>
  );
}
