import type { AskResponse, ChartSpec, EvalRun, SchemaResponse } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Can't reach the server. Is the backend running?");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "That input isn't valid.";
    } catch {}
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

export const ask = (question: string, session_id: string, no_clarify = false) =>
  request<AskResponse>("/ask", { method: "POST", body: JSON.stringify({ question, session_id, no_clarify }) });

export const runSql = (sql: string) =>
  request<{ sql: string; columns: string[]; rows: unknown[][]; chart_spec: ChartSpec }>("/run-sql", {
    method: "POST",
    body: JSON.stringify({ sql }),
  });

export const sendFeedback = (query_id: number, rating: 1 | -1) =>
  request<{ ok: boolean; saved_example: boolean }>("/feedback", { method: "POST", body: JSON.stringify({ query_id, rating }) });

export const getSchema = () => request<SchemaResponse>("/schema");
export const getExamples = () => request<{ examples: string[] }>("/examples");
export const getEvalRuns = () => request<{ runs: EvalRun[] }>("/eval/runs");
