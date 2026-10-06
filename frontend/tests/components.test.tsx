import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { toPoints } from "@/components/Chart";
import ResultCard, { type Message } from "@/components/ResultCard";
import ResultTable from "@/components/ResultTable";
import Sidebar from "@/components/Sidebar";
import SqlBlock from "@/components/SqlBlock";
import { ApiError } from "@/lib/api";
import type { AskResponse } from "@/lib/types";

vi.mock("@/lib/api", async (orig) => {
  const real = await orig<typeof import("@/lib/api")>();
  return { ...real, runSql: vi.fn(), sendFeedback: vi.fn() };
});
// Recharts needs real layout; the chart marks are covered by the toPoints tests and manual browser checks.
vi.mock("@/components/Chart", async (orig) => {
  const real = await orig<typeof import("@/components/Chart")>();
  return { ...real, default: () => <div data-testid="chart" /> };
});

import { runSql, sendFeedback } from "@/lib/api";

const ok = (over: Partial<AskResponse> = {}): AskResponse => ({
  status: "ok",
  answer: "The USA has the most customers.",
  sql: "SELECT country, count(*) AS n FROM data.customer GROUP BY country LIMIT 500",
  columns: ["country", "n"],
  rows: [["USA", 13], ["Canada", 8]],
  chart_spec: { type: "bar", x: "country", y: "n" },
  retries: 0,
  query_id: 7,
  error: null,
  clarification: null,
  ...over,
});
const msg = (result: AskResponse): Message => ({ id: "1", question: "q", status: "done", result });

beforeEach(() => vi.clearAllMocks());

describe("toPoints", () => {
  it("maps columns to x/y and drops non-numeric y", () => {
    const pts = toPoints({ type: "bar", x: "c", y: "n" }, ["c", "n"], [["a", 1], ["b", "x"], ["c", "3"]]);
    expect(pts).toEqual([{ x: "a", y: 1 }, { x: "c", y: 3 }]);
  });
  it("returns nothing for unknown columns", () => {
    expect(toPoints({ type: "bar", x: "zz", y: "n" }, ["c", "n"], [["a", 1]])).toEqual([]);
  });
});

describe("ResultTable", () => {
  it("shows an empty-result message", () => {
    render(<ResultTable columns={["a"]} rows={[]} />);
    expect(screen.getByText(/returned no rows/i)).toBeInTheDocument();
  });
  it("does not put thousands separators in years or ids but does in amounts", () => {
    render(<ResultTable columns={["year", "customer_id", "revenue"]} rows={[[2021, 1234, 12345]]} />);
    expect(screen.getByText("2021")).toBeInTheDocument();
    expect(screen.getByText("1234")).toBeInTheDocument();
    expect(screen.getByText("12,345")).toBeInTheDocument();
  });
  it("renders null as a dash", () => {
    render(<ResultTable columns={["a"]} rows={[[null]]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });
  it("paginates and notes the 500-row cap", async () => {
    const rows = Array.from({ length: 500 }, (_, i) => [`r${i}`]);
    render(<ResultTable columns={["a"]} rows={rows} />);
    expect(screen.getByText(/Rows 1–15 of 500/)).toBeInTheDocument();
    expect(screen.getByText(/capped at 500 rows/)).toBeInTheDocument();
    expect(screen.getByText("r0")).toBeInTheDocument();
    expect(screen.queryByText("r15")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("r15")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });
});

describe("ResultCard", () => {
  it("renders answer, table, chart, collapsed SQL and feedback", () => {
    render(<ResultCard msg={msg(ok())} />);
    expect(screen.getByText("The USA has the most customers.")).toBeInTheDocument();
    expect(screen.getByText("USA")).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /show sql/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Good answer" })).toBeInTheDocument();
    expect(screen.queryByText(/retries:/)).not.toBeInTheDocument();
  });
  it("shows the retries badge when self-correction kicked in", () => {
    render(<ResultCard msg={msg(ok({ retries: 1 }))} />);
    expect(screen.getByText("retries: 1")).toBeInTheDocument();
  });
  it("shows a clear failure with the last SQL attempted", () => {
    render(<ResultCard msg={msg(ok({ status: "error", answer: "I couldn't build a working query.", sql: "SELECT nope", error: 'column "nope" does not exist', retries: 2, rows: [], columns: [] }))} />);
    expect(screen.getByText(/couldn't build a working query/i)).toBeInTheDocument();
    expect(screen.getByText(/does not exist/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("SELECT nope");
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });
  it("labels blocked queries as blocked", () => {
    render(<ResultCard msg={msg(ok({ status: "blocked", sql: "DROP TABLE x", error: "only SELECT is allowed", rows: [], columns: [] }))} />);
    expect(screen.getByText(/blocked by the safety layer/i)).toBeInTheDocument();
  });
  it("shows the loading state and network errors", () => {
    const { rerender } = render(<ResultCard msg={{ id: "1", question: "q", status: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent(/checking the query/i);
    rerender(<ResultCard msg={{ id: "1", question: "q", status: "network_error", networkError: "Can't reach the server." }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach the server.");
  });
  it("sends feedback once and then locks the buttons", async () => {
    vi.mocked(sendFeedback).mockResolvedValue({ ok: true, saved_example: false });
    render(<ResultCard msg={msg(ok())} />);
    await userEvent.click(screen.getByRole("button", { name: "Good answer" }));
    expect(sendFeedback).toHaveBeenCalledWith(7, 1);
    expect(await screen.findByText(/thanks for the feedback/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bad answer" })).toBeDisabled();
  });
  it("lets the user retry feedback after a failure", async () => {
    vi.mocked(sendFeedback).mockRejectedValue(new Error("x"));
    render(<ResultCard msg={msg(ok())} />);
    await userEvent.click(screen.getByRole("button", { name: "Bad answer" }));
    expect(await screen.findByText(/couldn’t save feedback/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Bad answer" })).toBeEnabled();
  });
  it("replaces the table with the edited query's results", async () => {
    vi.mocked(runSql).mockResolvedValue({ sql: "SELECT 1 LIMIT 500", columns: ["x"], rows: [["EDITED"]], chart_spec: { type: "none" } });
    render(<ResultCard msg={msg(ok())} />);
    await userEvent.click(screen.getByRole("button", { name: /show sql/i }));
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(await screen.findByText("EDITED")).toBeInTheDocument();
    expect(screen.getByText(/edited query/i)).toBeInTheDocument();
  });
});

describe("clarification and feedback (F9, F10)", () => {
  const clarify = ok({ status: "clarify", answer: "What does best mean?", sql: null, columns: [], rows: [], query_id: 9,
    clarification: { question: "What does best mean?", options: ["By total revenue", "By number of orders"] } });

  it("shows the question with clickable options instead of results", async () => {
    const onChoose = vi.fn();
    render(<ResultCard msg={{ id: "1", question: "best customers?", status: "done", result: clarify }} onChoose={onChoose} />);
    expect(screen.getByText("What does best mean?")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "By number of orders" }));
    expect(onChoose).toHaveBeenCalledWith("best customers? (By number of orders)");
  });
  it("tells the user when a thumbs-up was saved as an example", async () => {
    vi.mocked(sendFeedback).mockResolvedValue({ ok: true, saved_example: true });
    render(<ResultCard msg={msg(ok())} />);
    await userEvent.click(screen.getByRole("button", { name: "Good answer" }));
    expect(await screen.findByText(/saved as an example/i)).toBeInTheDocument();
  });
  it("does not claim an example was saved when it was not", async () => {
    vi.mocked(sendFeedback).mockResolvedValue({ ok: true, saved_example: false });
    render(<ResultCard msg={msg(ok())} />);
    await userEvent.click(screen.getByRole("button", { name: "Bad answer" }));
    expect(await screen.findByText("Thanks for the feedback")).toBeInTheDocument();
    expect(screen.queryByText(/saved as an example/i)).not.toBeInTheDocument();
  });
});

describe("SqlBlock", () => {
  it("runs edited SQL and surfaces the safety/DB error", async () => {
    vi.mocked(runSql).mockRejectedValue(new ApiError("blocked: only SELECT is allowed"));
    render(<SqlBlock sql="SELECT 1" defaultOpen />);
    const box = screen.getByRole("textbox");
    await userEvent.clear(box);
    await userEvent.type(box, "DROP TABLE x");
    await userEvent.click(screen.getByRole("button", { name: "Run" }));
    expect(runSql).toHaveBeenCalledWith("DROP TABLE x");
    expect(await screen.findByRole("alert")).toHaveTextContent("blocked: only SELECT is allowed");
  });
  it("offers Reset only after an edit and restores the original", async () => {
    render(<SqlBlock sql="SELECT 1" defaultOpen />);
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), " -- x");
    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByRole("textbox")).toHaveValue("SELECT 1");
  });
  it("disables Run for empty SQL", async () => {
    render(<SqlBlock sql="SELECT 1" defaultOpen />);
    await userEvent.clear(screen.getByRole("textbox"));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Run/ })).toBeDisabled());
  });
});

describe("Sidebar", () => {
  const schema = {
    dataset: "Chinook",
    tables: [
      { name: "album", columns: [{ name: "title", type: "text", description: "Album title" }] },
      { name: "customer", columns: [{ name: "email", type: "text", description: "Contact address" }, { name: "city", type: "text", description: null }] },
    ],
  };
  it("lists examples and picks one on click", async () => {
    const onPick = vi.fn();
    render(<Sidebar schema={schema} examples={["How many customers?"]} onPick={onPick} loadError={false} />);
    await userEvent.click(screen.getByRole("button", { name: "How many customers?" }));
    expect(onPick).toHaveBeenCalledWith("How many customers?");
  });
  it("searches tables and columns (including descriptions)", async () => {
    render(<Sidebar schema={schema} examples={[]} onPick={() => {}} loadError={false} />);
    await userEvent.type(screen.getByRole("searchbox"), "contact");
    expect(screen.getByText("customer")).toBeInTheDocument();
    expect(screen.getByText("email")).toBeInTheDocument();
    expect(screen.queryByText("city")).not.toBeInTheDocument();
    expect(screen.queryByText("album")).not.toBeInTheDocument();
  });
  it("says so when nothing matches or loading failed", async () => {
    const { rerender } = render(<Sidebar schema={schema} examples={[]} onPick={() => {}} loadError={false} />);
    await userEvent.type(screen.getByRole("searchbox"), "zzzz");
    expect(screen.getByText("No matches.")).toBeInTheDocument();
    rerender(<Sidebar schema={null} examples={[]} onPick={() => {}} loadError />);
    expect(screen.getByText(/couldn’t load the schema/i)).toBeInTheDocument();
  });
});
