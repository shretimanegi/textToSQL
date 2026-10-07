import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import EvalPage from "@/app/eval/page";
import type { EvalRun } from "@/lib/types";

vi.mock("@/components/Chart", () => ({ default: () => <div data-testid="chart" /> }));
vi.mock("@/lib/api", () => ({ getEvalRuns: vi.fn() }));
import { getEvalRuns } from "@/lib/api";

const run = (key: string, accuracy: number, model: string): EvalRun => ({
  id: 1, key, name: key, model, dataset: "bird_dev_200", accuracy, n_questions: 200, created_at: "2026-10-07",
  by_difficulty: null, avg_latency_ms: 5000, avg_input_tokens: 800, avg_cost_usd: null, retrieval: null, outcomes: null,
});

beforeEach(() => vi.clearAllMocks());

describe("Evaluation page", () => {
  it("shows measured rows with their model and 'Not run yet' for the rest", async () => {
    vi.mocked(getEvalRuns).mockResolvedValue({ runs: [run("f1", 0.67, "model-a")] });
    render(<EvalPage />);
    expect(await screen.findByText("67.0%")).toBeInTheDocument();
    expect(screen.getByText("model-a")).toBeInTheDocument();
    expect(screen.getAllByText("Not run yet")).toHaveLength(3);
  });
  it("computes the gain over the previous row when both used the same model", async () => {
    vi.mocked(getEvalRuns).mockResolvedValue({ runs: [run("f1", 0.6, "m"), run("f2", 0.65, "m")] });
    render(<EvalPage />);
    expect(await screen.findByText("+5.0 pts")).toBeInTheDocument();
  });
  it("does not claim a gain across different models", async () => {
    vi.mocked(getEvalRuns).mockResolvedValue({ runs: [run("f1", 0.67, "model-a"), run("f2", 0.7, "model-b")] });
    render(<EvalPage />);
    expect(await screen.findByText("different model")).toBeInTheDocument();
    expect(screen.queryByText(/pts/)).not.toBeInTheDocument();
  });
  it("shows an error when the API is unreachable", async () => {
    vi.mocked(getEvalRuns).mockRejectedValue(new Error("Can't reach the server."));
    render(<EvalPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the server.");
  });
});
