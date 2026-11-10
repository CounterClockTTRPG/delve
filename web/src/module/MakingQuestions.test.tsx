import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import MakingQuestions, { type MakingQuestionsEntry } from "./MakingQuestions";

const MODULE = "mod_1";
const QUESTIONS = `/api/modules/${MODULE}/questions`;
const ANSWERS = "/api/conversions/cnv_1/questions";

const asked: MakingQuestionsEntry = {
  conversion_id: "cnv_1",
  questions: [
    { id: "q1", text: "Should Grik bargain?", default: "He bargains for his life.", answer: null },
    { id: "q2", text: "Is the dragon real?", default: "No, a carving.", answer: "Yes, a young one." },
  ],
  remarks: [],
};

let fetchMock: ReturnType<typeof vi.fn>;
let listed: MakingQuestionsEntry[];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  listed = [asked];
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (method === "GET" && path === QUESTIONS) return json(200, listed);
    if (method === "PUT" && path === ANSWERS) return json(200, { ...asked, remarks: ["More kobolds."] });
    return json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderQuestions() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MakingQuestions moduleId={MODULE} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("MakingQuestions", () => {
  it("lists the questions with the defaults filled in, and the answers given", async () => {
    renderQuestions();
    expect(await screen.findByRole("region", { name: "Questions from making this module" })).toBeTruthy();
    expect((screen.getByLabelText("Should Grik bargain?") as HTMLInputElement).value).toBe("He bargains for his life.");
    expect((screen.getByLabelText("Is the dragon real?") as HTMLInputElement).value).toBe("Yes, a young one.");
  });

  it("sends the answers and a remark, and says they are in the notes", async () => {
    renderQuestions();
    fireEvent.change(await screen.findByLabelText("Should Grik bargain?"), { target: { value: "He fights." } });
    fireEvent.change(screen.getByLabelText("Remarks"), { target: { value: "More kobolds." } });
    fireEvent.click(screen.getByRole("button", { name: "Save the answers" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(JSON.parse(String(init.body))).toEqual({
      answers: { q1: "He fights.", q2: "Yes, a young one." },
      remarks: ["More kobolds."],
    });
    expect(await screen.findByText("Saved in the DM-only text “Notes from making this module”.")).toBeTruthy();
  });

  it("shows nothing for a module made without questions", async () => {
    listed = [];
    const { container } = renderQuestions();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });

  it("lists a thorough conversion's doubts with their pages and kinds, its cost, and tells the DM", async () => {
    let told = false;
    const doubted: MakingQuestionsEntry = {
      conversion_id: "cnv_2",
      questions: [],
      remarks: [],
      told: false,
      cost_usd: 42.5,
      doubts: [
        { piece: "clean-1", part: "haunted-house", pages: [3, 4], kind: "checker-flag", text: "Key 3 covers 80%." },
        { piece: "sketch-ship", part: "sea-ghost", pages: [], kind: "sketched-map", text: "No map in the book." },
      ],
    };
    listed = [doubted];
    fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET" && path === QUESTIONS) return json(200, listed);
      if (method === "POST" && path === "/api/conversions/cnv_2/tell-dm") {
        told = true;
        listed = [{ ...doubted, told: true }];
        return json(200, listed[0]);
      }
      return json(404, { error: "not found" });
    });
    renderQuestions();
    const section = await screen.findByRole("region", { name: /Doubts from the conversion \(2\)/ });
    expect(section.textContent).toContain("Cost: $42.50");
    expect(screen.queryByRole("region", { name: "Questions from making this module" })).toBeNull();
    expect(screen.getByText("Key 3 covers 80%.")).toBeTruthy();
    expect(screen.getByText("Flagged by the text check")).toBeTruthy();
    expect(screen.getByText("Sketched map")).toBeTruthy();
    expect(screen.getByRole("link", { name: "4" }).getAttribute("href")).toBe(`/api/modules/${MODULE}/assets/source-pdf#page=4`);
    fireEvent.click(screen.getByRole("button", { name: "Tell the DM" }));
    await waitFor(() => expect(told).toBe(true));
    expect(await screen.findByText(/Told the DM: they are in the DM-only text/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Tell the DM" })).toBeNull();
  });

  describe("closing", () => {
    const CLOSED = "/api/conversions/cnv_3/closed";
    const both: MakingQuestionsEntry = {
      conversion_id: "cnv_3",
      questions: [{ id: "q1", text: "Should Grik bargain?", default: "He bargains.", answer: null }],
      remarks: [],
      told: false,
      cost_usd: null,
      closed: [],
      doubts: [
        { piece: "clean-1", part: "haunted-house", pages: [3], kind: "checker-flag", text: "Key 3 covers 80%." },
        { piece: "sketch-ship", part: "sea-ghost", pages: [], kind: "sketched-map", text: "No map in the book." },
      ],
    };
    let sent: string[][];

    beforeEach(() => {
      sent = [];
      listed = [both];
      fetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        if (method === "GET" && path === QUESTIONS) return json(200, listed);
        if (method === "PUT" && path === CLOSED) {
          const closed = JSON.parse(String(init?.body)).closed as string[];
          sent.push(closed);
          listed = [{ ...both, closed }];
          return json(200, listed[0]);
        }
        return json(404, { error: "not found" });
      });
    });

    const doubts = () => screen.getByTestId("conversion-doubts");

    it("closes one doubt, and folds when all are closed", async () => {
      renderQuestions();
      await screen.findByText("Key 3 covers 80%.");
      fireEvent.click(within(screen.getByText("Key 3 covers 80%.").closest("li")!).getByRole("button", { name: "Close" }));
      await waitFor(() => expect(sent).toEqual([["doubt:0"]]));
      expect(await within(doubts()).findByRole("button", { name: "Reopen" })).toBeTruthy();
      expect(within(doubts()).getByText("Dealt with")).toBeTruthy();
      expect(screen.queryByText("Key 3 covers 80%.")).toBeNull();
      fireEvent.click(within(screen.getByText("No map in the book.").closest("li")!).getByRole("button", { name: "Close" }));
      await waitFor(() => expect(sent.at(-1)).toEqual(["doubt:0", "doubt:1"]));
      expect(await within(doubts()).findByText("All 2 dealt with")).toBeTruthy();
      expect(within(doubts()).queryByRole("button", { name: "Tell the DM" })).toBeNull();
      // The questions are a box of their own, still open.
      expect(screen.getByLabelText("Should Grik bargain?")).toBeTruthy();
      fireEvent.click(within(doubts()).getByRole("button", { name: "Show" }));
      expect(within(doubts()).getAllByRole("button", { name: "Reopen" })).toHaveLength(2);
      fireEvent.click(within(doubts()).getByRole("button", { name: "Hide" }));
      expect(within(doubts()).getByText("All 2 dealt with")).toBeTruthy();
    });

    it("close all", async () => {
      renderQuestions();
      await screen.findByText("Key 3 covers 80%.");
      fireEvent.click(within(doubts()).getByRole("button", { name: "Close all" }));
      await waitFor(() => expect(sent).toEqual([["doubt:0", "doubt:1"]]));
      expect(await within(doubts()).findByText("All 2 dealt with")).toBeTruthy();
      const questions = screen.getByRole("region", { name: "Questions from making this module" });
      fireEvent.click(within(questions).getByRole("button", { name: "Close all" }));
      await waitFor(() => expect(sent.at(-1)).toEqual(["doubt:0", "doubt:1", "question:q1"]));
      expect(await within(questions).findByText("All 1 dealt with")).toBeTruthy();
      expect(screen.queryByLabelText("Should Grik bargain?")).toBeNull();
    });

    it("reopen", async () => {
      listed = [{ ...both, closed: ["question:q1", "doubt:1"] }];
      renderQuestions();
      const questions = await screen.findByRole("region", { name: "Questions from making this module" });
      expect(within(questions).getByText("All 1 dealt with")).toBeTruthy();
      fireEvent.click(within(questions).getByRole("button", { name: "Show" }));
      fireEvent.click(within(questions).getByRole("button", { name: "Reopen" }));
      await waitFor(() => expect(sent).toEqual([["doubt:1"]]));
      expect(await screen.findByLabelText("Should Grik bargain?")).toBeTruthy();
      expect(screen.getByText("Key 3 covers 80%.")).toBeTruthy();
      expect(screen.queryByText("No map in the book.")).toBeNull();
      fireEvent.click(within(doubts()).getByRole("button", { name: "Reopen" }));
      await waitFor(() => expect(sent.at(-1)).toEqual([]));
      expect(await screen.findByText("No map in the book.")).toBeTruthy();
    });
  });
});
