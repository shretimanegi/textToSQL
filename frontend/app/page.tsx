"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import ResultCard, { type Message } from "@/components/ResultCard";
import Sidebar from "@/components/Sidebar";
import { ApiError, ask, getExamples, getSchema } from "@/lib/api";
import type { SchemaResponse } from "@/lib/types";

function sessionId(): string {
  try {
    let id = sessionStorage.getItem("session_id");
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem("session_id", id);
    }
    return id;
  } catch {
    return "anon";
  }
}

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [examples, setExamples] = useState<string[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    getSchema().then(setSchema).catch(() => setLoadError(true));
    getExamples().then((r) => setExamples(r.examples)).catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const submit = useCallback(
    async (question: string, resolved = false) => {
      const q = question.trim();
      if (!q || busy) return;
      const id = crypto.randomUUID();
      setBusy(true);
      setInput("");
      setDrawer(false);
      setMessages((m) => [...m, { id, question: q, status: "loading" }]);
      try {
        const result = await ask(q, sessionId(), resolved);
        setMessages((m) => m.map((x) => (x.id === id ? { ...x, status: "done", result } : x)));
      } catch (e) {
        const networkError = e instanceof ApiError ? e.message : "Something went wrong.";
        setMessages((m) => m.map((x) => (x.id === id ? { ...x, status: "network_error", networkError } : x)));
      } finally {
        setBusy(false);
      }
    },
    [busy],
  );

  const sidebar = <Sidebar schema={schema} examples={examples} onPick={submit} loadError={loadError} />;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2.5">
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => setDrawer(true)} className="rounded-lg border border-line px-3 py-2 text-sm md:hidden" aria-label="Open tables and examples">
            ☰
          </button>
          <h1 className="text-base font-semibold">Text-to-SQL Assistant</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-2 text-ink2">
            <span className="hidden sm:inline">Dataset</span>
            <select className="rounded-lg border border-line bg-surface px-2 py-1.5 text-ink" defaultValue="chinook" aria-label="Dataset">
              <option value="chinook">Chinook (sample)</option>
              <option value="csv" disabled>Upload CSV (coming soon)</option>
            </select>
          </label>
          <Link href="/eval" className="rounded-lg px-2 py-1.5 text-accent hover:bg-surface2">Evaluation</Link>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-80 shrink-0 border-r border-line bg-bg md:block">{sidebar}</aside>

        {drawer && (
          <div className="fixed inset-0 z-20 md:hidden" role="dialog" aria-modal="true" aria-label="Tables and examples">
            <button type="button" className="absolute inset-0 bg-black/40" onClick={() => setDrawer(false)} aria-label="Close" />
            <div className="absolute inset-y-0 left-0 w-[85%] max-w-xs bg-bg shadow-xl">{sidebar}</div>
          </div>
        )}

        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto px-4 py-6">
            <div className="mx-auto flex max-w-3xl flex-col gap-6">
              {messages.length === 0 && (
                <div className="py-10 text-center">
                  <h2 className="text-2xl font-semibold">Ask your data anything</h2>
                  <p className="mx-auto mt-2 max-w-md text-ink2">
                    Type a question in plain English. You’ll get the answer, the table, a chart and the SQL behind it.
                  </p>
                  <div className="mx-auto mt-6 flex max-w-xl flex-wrap justify-center gap-2">
                    {examples.slice(0, 4).map((e) => (
                      <button key={e} type="button" onClick={() => submit(e)} className="rounded-full border border-line bg-surface px-3.5 py-2 text-sm hover:bg-surface2">
                        {e}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((m) => (
                <section key={m.id} className="flex flex-col gap-3" aria-label={m.question}>
                  <p className="max-w-[85%] self-end rounded-2xl rounded-br-md bg-accent px-4 py-2.5 text-sm text-accent-ink">{m.question}</p>
                  <ResultCard msg={m} onChoose={(q) => submit(q, true)} />
                </section>
              ))}
              <div ref={endRef} />
            </div>
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              // Read the live value: state can lag a keystroke when Enter follows typing immediately.
              submit(inputRef.current?.value ?? input);
            }}
            className="border-t border-line bg-surface px-4 py-3"
          >
            <div className="mx-auto flex max-w-3xl gap-2">
              <label htmlFor="q" className="sr-only">Your question</label>
              <input
                id="q"
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                maxLength={500}
                placeholder={messages.some((m) => m.result?.status === "ok") ? "Ask a follow-up, e.g. now only for 2024" : "e.g. Which genres have the most tracks?"}
                className="min-w-0 flex-1 rounded-xl border border-line bg-bg px-4 py-3 text-base text-ink placeholder:text-ink3"
                autoComplete="off"
              />
              <button type="submit" disabled={busy || !input.trim()} className="rounded-xl bg-accent px-5 py-3 text-sm font-medium text-accent-ink disabled:opacity-50">
                {busy ? "Working…" : "Ask"}
              </button>
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}
