"use client";

import { useState } from "react";
import { sendFeedback } from "@/lib/api";
import type { AskResponse, ChartSpec } from "@/lib/types";
import Chart from "./Chart";
import ResultTable from "./ResultTable";
import SqlBlock from "./SqlBlock";

export type Message = {
  id: string;
  question: string;
  status: "loading" | "done" | "network_error";
  result?: AskResponse;
  networkError?: string;
};

function Feedback({ queryId }: { queryId: number }) {
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [saved, setSaved] = useState(false);
  const [failed, setFailed] = useState(false);

  async function rate(r: 1 | -1) {
    if (rating !== null) return;
    setRating(r);
    setFailed(false);
    try {
      const res = await sendFeedback(queryId, r);
      setSaved(res.saved_example);
    } catch {
      setRating(null);
      setFailed(true);
    }
  }

  const btn = (r: 1 | -1, label: string, icon: string) => (
    <button
      type="button"
      onClick={() => rate(r)}
      disabled={rating !== null}
      aria-pressed={rating === r}
      aria-label={label}
      className={`h-9 w-9 rounded-lg border text-base ${rating === r ? "border-accent bg-surface2" : "border-line"} ${rating === null ? "hover:bg-surface2" : "opacity-60"}`}
    >
      <span aria-hidden>{icon}</span>
    </button>
  );

  return (
    <div className="flex items-center gap-1.5">
      {btn(1, "Good answer", "👍")}
      {btn(-1, "Bad answer", "👎")}
      {rating !== null && (
        <span className="ml-1 text-xs text-ink2">{saved ? "Thanks — saved as an example for future questions" : "Thanks for the feedback"}</span>
      )}
      {failed && <span role="alert" className="ml-1 text-xs text-danger">Couldn’t save feedback</span>}
    </div>
  );
}

export default function ResultCard({ msg, onChoose }: { msg: Message; onChoose?: (question: string) => void }) {
  const [edited, setEdited] = useState<{ sql: string; columns: string[]; rows: unknown[][]; chart_spec: ChartSpec } | null>(null);

  if (msg.status === "loading") {
    return (
      <div className="rounded-2xl border border-line bg-surface p-5" role="status" aria-live="polite">
        <div className="flex items-center gap-2 text-sm text-ink2">
          <span className="inline-flex gap-1" aria-hidden>
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink3 [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink3 [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink3" />
          </span>
          Writing and checking the query…
        </div>
      </div>
    );
  }

  if (msg.status === "network_error" || !msg.result) {
    return (
      <div role="alert" className="rounded-2xl border border-line bg-danger-bg p-5 text-sm text-danger">
        <span aria-hidden>⚠ </span>
        {msg.networkError ?? "Something went wrong."}
      </div>
    );
  }

  const r = msg.result;

  if (r.status === "clarify" && r.clarification) {
    return (
      <div className="rounded-2xl border border-line bg-surface p-5">
        <p className="font-medium text-ink">{r.clarification.question}</p>
        <p className="mt-1 text-sm text-ink2">Your question could mean a few things. Pick one and I’ll run it.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {r.clarification.options.map((o) => (
            <button
              key={o}
              type="button"
              onClick={() => onChoose?.(`${msg.question} (${o})`)}
              className="rounded-full border border-line bg-bg px-4 py-2 text-sm text-ink hover:bg-surface2"
            >
              {o}
            </button>
          ))}
        </div>
      </div>
    );
  }

  if (r.status !== "ok") {
    const blocked = r.status === "blocked";
    return (
      <div className="rounded-2xl border border-line bg-surface p-5">
        <p className="flex items-start gap-2 font-medium text-danger" role="alert">
          <span aria-hidden>{blocked ? "⛔" : "⚠"}</span>
          <span>
            {blocked ? "Blocked by the safety layer" : r.answer}
            {r.retries > 0 && <span className="ml-2 rounded-full bg-surface2 px-2 py-0.5 text-xs font-normal text-ink2">retries: {r.retries}</span>}
          </span>
        </p>
        {r.error && <p className="mt-2 text-sm text-ink2">{r.error}</p>}
        {r.sql && (
          <>
            <p className="mt-3 text-xs text-ink3">Last SQL attempted:</p>
            <SqlBlock sql={r.sql} defaultOpen onEdited={(e) => setEdited(e)} />
          </>
        )}
        {edited && (
          <>
            <ResultTable columns={edited.columns} rows={edited.rows} />
            <Chart spec={edited.chart_spec} columns={edited.columns} rows={edited.rows} />
          </>
        )}
      </div>
    );
  }

  const view = edited ?? { sql: r.sql ?? "", columns: r.columns, rows: r.rows, chart_spec: r.chart_spec };

  return (
    <article className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="text-base font-medium leading-snug text-ink">{r.answer}</p>
        {r.retries > 0 && (
          <span className="shrink-0 rounded-full bg-surface2 px-2.5 py-1 text-xs text-ink2" title="The first query failed and was automatically corrected">
            retries: {r.retries}
          </span>
        )}
      </div>
      {edited && <p className="mt-1 text-xs text-ink3">Showing results of your edited query.</p>}
      <ResultTable columns={view.columns} rows={view.rows} />
      <Chart spec={view.chart_spec} columns={view.columns} rows={view.rows} />
      {r.sql && <SqlBlock key={r.sql} sql={r.sql} onEdited={(e) => setEdited(e)} />}
      {r.query_id !== null && (
        <div className="mt-3 border-t border-line pt-3">
          <Feedback queryId={r.query_id} />
        </div>
      )}
    </article>
  );
}
