"use client";

import { useMemo, useState } from "react";
import type { SchemaResponse } from "@/lib/types";

export default function Sidebar({
  schema,
  examples,
  onPick,
  loadError,
}: {
  schema: SchemaResponse | null;
  examples: string[];
  onPick: (q: string) => void;
  loadError: boolean;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const q = query.trim().toLowerCase();

  const tables = useMemo(() => {
    if (!schema) return [];
    if (!q) return schema.tables;
    return schema.tables
      .map((t) => {
        if (t.name.toLowerCase().includes(q)) return t;
        const cols = t.columns.filter((c) => c.name.toLowerCase().includes(q) || (c.description ?? "").toLowerCase().includes(q));
        return cols.length ? { ...t, columns: cols } : null;
      })
      .filter((t): t is NonNullable<typeof t> => t !== null);
  }, [schema, q]);

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      <section aria-labelledby="ex-h">
        <h2 id="ex-h" className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink3">Try asking</h2>
        <ul className="flex flex-col gap-1.5">
          {examples.map((e) => (
            <li key={e}>
              <button type="button" onClick={() => onPick(e)} className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-left text-sm text-ink hover:bg-surface2">
                {e}
              </button>
            </li>
          ))}
          {examples.length === 0 && <li className="text-sm text-ink3">{loadError ? "Couldn’t load examples." : "Loading…"}</li>}
        </ul>
      </section>

      <section aria-labelledby="schema-h" className="min-h-0">
        <h2 id="schema-h" className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink3">
          Tables{schema ? ` · ${schema.dataset}` : ""}
        </h2>
        <label htmlFor="schema-search" className="sr-only">Search tables and columns</label>
        <input
          id="schema-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search tables and columns"
          className="mb-2 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink3"
        />
        {loadError && <p className="text-sm text-danger">Couldn’t load the schema.</p>}
        <ul className="flex flex-col gap-0.5">
          {tables.map((t) => {
            const expanded = q ? true : open[t.name];
            return (
              <li key={t.name}>
                <button
                  type="button"
                  aria-expanded={!!expanded}
                  onClick={() => setOpen({ ...open, [t.name]: !open[t.name] })}
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm font-medium text-ink hover:bg-surface2"
                >
                  <span>{t.name}</span>
                  <span className="text-xs text-ink3">{t.columns.length}</span>
                </button>
                {expanded && (
                  <ul className="mb-1 ml-2 border-l border-line pl-2">
                    {t.columns.map((c) => (
                      <li key={c.name} title={c.description ?? undefined} className="flex items-baseline justify-between gap-2 py-0.5 text-xs">
                        <span className="text-ink2">{c.name}</span>
                        <span className="shrink-0 text-ink3">{c.type}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
          {schema && tables.length === 0 && <li className="px-2 text-sm text-ink3">No matches.</li>}
        </ul>
      </section>
    </div>
  );
}
