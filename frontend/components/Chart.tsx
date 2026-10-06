"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/types";

type Point = { x: string; y: number };

const fmt = (n: number) =>
  Math.abs(n) >= 1000 ? n.toLocaleString(undefined, { maximumFractionDigits: 1 }) : String(Math.round(n * 100) / 100);

const AXIS = { fill: "var(--text-secondary)", fontSize: 12 };

function ChartTooltip({ active, payload, yLabel }: { active?: boolean; payload?: { payload: Point }[]; yLabel: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <div className="text-ink2">{p.x}</div>
      <div className="mt-0.5 flex items-center gap-2 text-ink">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: "var(--series-1)" }} />
        <span className="font-medium tabular-nums">{fmt(p.y)}</span>
        <span className="text-ink2">{yLabel}</span>
      </div>
    </div>
  );
}

export function toPoints(spec: ChartSpec, columns: string[], rows: unknown[][]): Point[] {
  const xi = columns.indexOf(spec.x ?? "");
  const yi = columns.indexOf(spec.y ?? "");
  if (xi < 0 || yi < 0) return [];
  return rows
    .map((r) => ({ x: String(r[xi] ?? ""), y: Number(r[yi]) }))
    .filter((p) => Number.isFinite(p.y));
}

export default function Chart({ spec, columns, rows }: { spec: ChartSpec; columns: string[]; rows: unknown[][] }) {
  const data = toPoints(spec, columns, rows);
  if (spec.type === "none" || data.length < 2) return null;
  const yLabel = spec.y ?? "";
  const title = `${spec.type === "line" ? "Line" : "Bar"} chart of ${yLabel} by ${spec.x}`;

  if (spec.type === "line") {
    return (
      <figure aria-label={title} className="mt-4">
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
            <XAxis dataKey="x" tick={AXIS} tickLine={false} axisLine={false} minTickGap={24} interval="preserveStartEnd" />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} tickFormatter={fmt} />
            <Tooltip content={<ChartTooltip yLabel={yLabel} />} cursor={{ stroke: "var(--border)", strokeWidth: 1 }} />
            {/* ~10% wash under a 2px line; the end-dot carries a 2px surface ring */}
            <Area
              type="monotone"
              dataKey="y"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="var(--series-1)"
              fillOpacity={0.1}
              dot={(p: { cx?: number; cy?: number; index?: number }) =>
                p.index === data.length - 1 ? (
                  <circle key="end" cx={p.cx} cy={p.cy} r={4} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />
                ) : (
                  <g key={p.index} />
                )
              }
              activeDot={{ r: 4, fill: "var(--series-1)", stroke: "var(--surface-1)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
        <figcaption className="sr-only">{title}</figcaption>
      </figure>
    );
  }

  // Bars. Long or many category labels read better as horizontal bars.
  const longest = Math.max(...data.map((d) => d.x.length));
  const horizontal = data.length > 6 || longest > 12;
  const labelWidth = Math.min(170, Math.max(60, longest * 6.5));
  const showValues = data.length <= 12;

  if (horizontal) {
    const height = Math.max(160, data.length * 30 + 24);
    return (
      <figure aria-label={title} className="mt-4">
        <ResponsiveContainer width="100%" height={height}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: showValues ? 56 : 16, bottom: 4, left: 0 }} barCategoryGap={6}>
            <CartesianGrid horizontal={false} stroke="var(--grid)" strokeWidth={1} />
            <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} tickFormatter={fmt} />
            <YAxis
              type="category"
              dataKey="x"
              width={labelWidth}
              tick={AXIS}
              tickLine={false}
              axisLine={false}
              interval={0}
              tickFormatter={(v: string) => (v.length > 24 ? v.slice(0, 23) + "…" : v)}
            />
            <Tooltip content={<ChartTooltip yLabel={yLabel} />} cursor={{ fill: "var(--surface-2)", opacity: 0.6 }} />
            <Bar dataKey="y" fill="var(--series-1)" maxBarSize={20} radius={[0, 4, 4, 0]} isAnimationActive={false}>
              {showValues && (
                <LabelList dataKey="y" position="right" formatter={(v: unknown) => fmt(Number(v))} style={{ fill: "var(--text-secondary)", fontSize: 12 }} />
              )}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
        <figcaption className="sr-only">{title}</figcaption>
      </figure>
    );
  }

  return (
    <figure aria-label={title} className="mt-4">
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 20, right: 16, bottom: 4, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" strokeWidth={1} />
          <XAxis dataKey="x" tick={AXIS} tickLine={false} axisLine={false} interval={0} />
          <YAxis tick={AXIS} tickLine={false} axisLine={false} width={56} tickFormatter={fmt} />
          <Tooltip content={<ChartTooltip yLabel={yLabel} />} cursor={{ fill: "var(--surface-2)", opacity: 0.6 }} />
          <Bar dataKey="y" fill="var(--series-1)" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {showValues && (
              <LabelList dataKey="y" position="top" formatter={(v: unknown) => fmt(Number(v))} style={{ fill: "var(--text-secondary)", fontSize: 12 }} />
            )}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <figcaption className="sr-only">{title}</figcaption>
    </figure>
  );
}
