export type ChartSpec = { type: "line" | "bar" | "none"; x?: string; y?: string };

export type AskResponse = {
  status: "ok" | "blocked" | "error" | "clarify";
  answer: string;
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  chart_spec: ChartSpec;
  retries: number;
  query_id: number | null;
  error: string | null;
  clarification: { question: string; options: string[] } | null;
};

export type SchemaColumn = { name: string; type: string; description: string | null };
export type SchemaTable = { name: string; columns: SchemaColumn[] };
export type SchemaResponse = { dataset: string; tables: SchemaTable[] };

export type EvalRun = {
  id: number;
  key: string | null;
  name: string | null;
  model: string | null;
  dataset: string;
  accuracy: number | null;
  n_questions: number | null;
  created_at: string;
  by_difficulty: Record<string, { correct: number; n: number; accuracy: number }> | null;
  avg_latency_ms: number | null;
  avg_input_tokens: number | null;
  avg_cost_usd: number | null;
  retrieval: { table_recall: number; avg_tables_in_prompt: number; avg_tables_available: number } | null;
  outcomes: Record<string, number> | null;
};
