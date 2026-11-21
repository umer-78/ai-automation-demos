import { useId, useMemo, useState, type PointerEvent } from "react";
import { day } from "../lib/format";

/** One measure per chart, on its own axis, with the value under the pointer. Never two scales on one plot. */
export function DailyChart({ title, points, format, color }: {
  title: string; points: { date: string; value: number }[]; format: (n: number) => string; color: string;
}) {
  const W = 420, H = 124, L = 46, R = 8, T = 10, B = 20;
  const [hover, setHover] = useState<number | null>(null);
  const gradient = useId();
  const max = useMemo(() => niceMax(Math.max(0, ...points.map((p) => p.value))), [points]);
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, points.length - 1);
  const y = (v: number) => T + (1 - v / max) * (H - T - B);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const total = points.reduce((a, p) => a + p.value, 0);

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((px - L) / (W - L - R)) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };
  const h = hover != null ? points[hover] : null;

  return (
    <figure className="chart">
      <figcaption className="chart-head">
        <span>{title}</span>
        <span className="small">{h ? `${day(h.date)}: ${format(h.value)}` : `30-day total ${format(total)}`}</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} className="block w-full touch-none" role="img"
        aria-label={`${title}, ${day(points[0]?.date)} to ${day(points.at(-1)?.date)}. Highest ${format(Math.max(...points.map((p) => p.value)))}.`}
        onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity=".14" />
            <stop offset="1" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(max * f)} y2={y(max * f)} stroke="#0F2A3F" strokeOpacity={f === 0 ? 0.18 : 0.07} />
            <text x={L - 6} y={y(max * f) + 3.5} textAnchor="end" className="chart-tick">{format(max * f)}</text>
          </g>
        ))}
        <text x={L} y={H - 4} className="chart-tick">{day(points[0]?.date)}</text>
        <text x={W - R} y={H - 4} textAnchor="end" className="chart-tick">{day(points.at(-1)?.date)}</text>
        <path d={`${line} L${x(points.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill={`url(#${gradient})`} />
        <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {h && hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={T} y2={y(0)} stroke="#0F2A3F" strokeOpacity=".25" />
            <circle cx={x(hover)} cy={y(h.value)} r="4" fill={color} stroke="#fff" strokeWidth="2" />
          </g>
        )}
      </svg>
    </figure>
  );
}

/** Round an axis maximum up to a readable step (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8 or 10 times a power of ten). */
function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((s) => v / p <= s) ?? 10;
  return step * p;
}
