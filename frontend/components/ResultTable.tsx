"use client";

import { useState } from "react";

const PAGE_SIZE = 15;
const ROW_CAP = 500;

const isNum = (v: unknown) => typeof v === "number";

// Identifier-like integers (years, ids, codes) must not get thousands separators: 2021, not 2,021.
const NO_GROUPING = /(^|_|\b)(year|yr|id|ids|code|zip|postal|phone|number|no|num)(_|\b|$)|id$/i;

function cell(v: unknown, column: string): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    if (Number.isInteger(v) && NO_GROUPING.test(column)) return String(v);
    return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

export default function ResultTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const p = Math.min(page, pages - 1);
  const slice = rows.slice(p * PAGE_SIZE, (p + 1) * PAGE_SIZE);
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] === null || isNum(r[i])));

  if (rows.length === 0) {
    return <p className="mt-4 rounded-lg bg-surface2 px-3 py-3 text-sm text-ink2">The query ran fine but returned no rows.</p>;
  }

  return (
    <div className="mt-4">
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-max text-left text-sm">
          <thead className="bg-surface2 text-xs text-ink2">
            <tr>
              {columns.map((c, i) => (
                <th key={c + i} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${numeric[i] ? "text-right" : ""}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {slice.map((r, ri) => (
              <tr key={ri} className="border-t border-line">
                {r.map((v, ci) => (
                  <td key={ci} className={`max-w-[28rem] truncate px-3 py-1.5 ${numeric[ci] ? "text-right tabular-nums" : ""} ${v === null ? "text-ink3" : ""}`} title={String(v ?? "")}>
                    {cell(v, columns[ci])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-ink2">
        <span>
          {rows.length > PAGE_SIZE ? `Rows ${p * PAGE_SIZE + 1}–${Math.min(rows.length, (p + 1) * PAGE_SIZE)} of ${rows.length}` : `${rows.length} row${rows.length === 1 ? "" : "s"}`}
          {rows.length >= ROW_CAP && " · capped at 500 rows"}
        </span>
        {pages > 1 && (
          <span className="flex items-center gap-1">
            <button type="button" onClick={() => setPage(p - 1)} disabled={p === 0} className="rounded-md border border-line px-3 py-1.5 disabled:opacity-40 hover:bg-surface2">
              Previous
            </button>
            <span className="px-2 tabular-nums">
              {p + 1} / {pages}
            </span>
            <button type="button" onClick={() => setPage(p + 1)} disabled={p >= pages - 1} className="rounded-md border border-line px-3 py-1.5 disabled:opacity-40 hover:bg-surface2">
              Next
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
