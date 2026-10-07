"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Chart from "@/components/Chart";
import { getEvalRuns } from "@/lib/api";
import type { EvalRun } from "@/lib/types";

const CONFIGS = [
  { key: "f1", name: "F1 baseline (full schema)" },
  { key: "f2", name: "+ F2 schema retrieval" },
  { key: "f3", name: "+ F3 few-shot retrieval" },
  { key: "f4", name: "+ F4 self-correction" },
];

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);

export default function EvalPage() {
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getEvalRuns().then((r) => setRuns(r.runs)).catch((e) => setError(e.message));
  }, []);

  // Latest run per config key.
  const latest = new Map<string, EvalRun>();
  for (const r of runs ?? []) if (r.key) latest.set(r.key, r);
  const rows = CONFIGS.map((c, i) => {
    const run = latest.get(c.key) ?? null;
    const prev = i > 0 ? latest.get(CONFIGS[i - 1].key) : null;
    // A gain is only meaningful when both rows came from the same model.
    const sameModel = run != null && prev != null && run.model === prev.model;
    const delta = sameModel && run.accuracy != null && prev.accuracy != null ? (run.accuracy - prev.accuracy) * 100 : null;
    const crossModel = run != null && prev != null && !sameModel;
    return { ...c, run, delta, crossModel };
  });
  const measured = rows.filter((r) => r.run?.accuracy != null);
  const first = measured[0]?.run;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <Link href="/" className="text-sm text-accent hover:underline">← Back to the assistant</Link>
      <h1 className="mt-3 text-2xl font-semibold">Evaluation</h1>
      <p className="mt-2 max-w-2xl text-ink2">
        Execution accuracy on a fixed 200-question subset of the BIRD dev benchmark: a predicted query counts only if its result rows match the reference query’s rows.
        Each row adds one feature to the row above it, on the same questions.
      </p>

      {error && <p role="alert" className="mt-6 rounded-lg bg-danger-bg px-3 py-2 text-sm text-danger">{error}</p>}
      {!runs && !error && <p className="mt-6 text-ink2">Loading…</p>}

      {runs && (
        <>
          <div className="mt-6 overflow-x-auto rounded-xl border border-line bg-surface">
            <table className="w-full min-w-max text-left text-sm">
              <caption className="sr-only">Execution accuracy by configuration</caption>
              <thead className="bg-surface2 text-xs text-ink2">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Configuration</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Model</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Accuracy</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">vs previous</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Avg latency</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">Avg prompt tokens</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key} className="border-t border-line">
                    <th scope="row" className="px-4 py-3 font-medium">{r.name}</th>
                    {r.run ? (
                      <>
                        <td className="px-4 py-3 text-xs text-ink2">{r.run.model ?? "unknown"}</td>
                        <td className="px-4 py-3 text-right tabular-nums">
                          {pct(r.run.accuracy)} <span className="text-ink3">({Math.round((r.run.accuracy ?? 0) * (r.run.n_questions ?? 0))}/{r.run.n_questions})</span>
                        </td>
                        <td className={`px-4 py-3 text-right tabular-nums ${r.delta == null ? "text-ink3" : r.delta < 0 ? "text-danger" : "text-good"}`}>
                          {r.crossModel ? "different model" : r.delta == null ? "—" : `${r.delta > 0 ? "+" : ""}${r.delta.toFixed(1)} pts`}
                        </td>
                        <td className="px-4 py-3 text-right tabular-nums">{r.run.avg_latency_ms != null ? `${(r.run.avg_latency_ms / 1000).toFixed(1)} s` : "—"}</td>
                        <td className="px-4 py-3 text-right tabular-nums">{r.run.avg_input_tokens != null ? Math.round(r.run.avg_input_tokens).toLocaleString() : "—"}</td>
                      </>
                    ) : (
                      <td colSpan={5} className="px-4 py-3 text-ink3">Not run yet</td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {measured.length >= 2 && (
            <div className="mt-6 rounded-xl border border-line bg-surface p-4">
              <h2 className="text-sm font-medium">Execution accuracy by configuration</h2>
              <Chart
                spec={{ type: "bar", x: "Configuration", y: "Accuracy (%)" }}
                columns={["Configuration", "Accuracy (%)"]}
                rows={measured.map((r) => [r.key?.toUpperCase(), Math.round((r.run!.accuracy ?? 0) * 1000) / 10])}
              />
            </div>
          )}

          {first && (
            <p className="mt-6 text-xs text-ink3">
              Dataset: {first.dataset} · the BIRD hint is included in the prompt. Rows are only compared when they used the same model. Questions whose reference SQL cannot run on PostgreSQL
              (8% of the benchmark) are excluded, so compare rows to each other rather than to the public leaderboard.
              Latency here includes free-tier rate limiting.
            </p>
          )}
        </>
      )}
    </div>
  );
}
