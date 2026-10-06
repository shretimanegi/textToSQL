"use client";

import { useState } from "react";
import { ApiError, runSql } from "@/lib/api";
import type { ChartSpec } from "@/lib/types";

type Edited = { sql: string; columns: string[]; rows: unknown[][]; chart_spec: ChartSpec };

export default function SqlBlock({
  sql,
  defaultOpen = false,
  onEdited,
}: {
  sql: string;
  defaultOpen?: boolean;
  onEdited?: (r: Edited) => void;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [text, setText] = useState(sql);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changed = text.trim() !== sql.trim();

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const r = await runSql(text);
      setText(r.sql);
      onEdited?.(r);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong running that query.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md py-1 text-xs font-medium text-ink2 hover:text-ink"
      >
        <span aria-hidden className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
        {open ? "Hide SQL" : "Show SQL"}
      </button>
      {open && (
        <div className="mt-1.5">
          <label htmlFor={`sql-${sql.length}`} className="sr-only">
            SQL query (editable)
          </label>
          <textarea
            id={`sql-${sql.length}`}
            value={text}
            onChange={(e) => setText(e.target.value)}
            spellCheck={false}
            rows={Math.min(14, Math.max(3, text.split("\n").length + 1))}
            className="w-full resize-y rounded-lg border border-line bg-surface2 p-3 font-mono text-[13px] leading-relaxed text-ink"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={run}
              disabled={running || !text.trim()}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-ink disabled:opacity-50"
            >
              {running ? "Running…" : "Run"}
            </button>
            {changed && (
              <button type="button" onClick={() => { setText(sql); setError(null); }} className="rounded-lg border border-line px-3 py-2 text-sm text-ink2 hover:bg-surface2">
                Reset
              </button>
            )}
            <span className="text-xs text-ink3">Edits go through the same safety checks: one SELECT, 5 s limit, 500 rows.</span>
          </div>
          {error && (
            <p role="alert" className="mt-2 rounded-lg bg-danger-bg px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
