import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Conversion } from "../api";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import type { NovelSource } from "./api";
import NovelizeForm, { defaultChoices } from "./NovelizeForm";

afterEach(() => {
  vi.unstubAllGlobals();
});

const CAMPAIGN: NovelSource = { kind: "campaign", id: "cmp_00000000000a" };
const MODULE: NovelSource = { kind: "module", id: "mod_00000000000a" };

const running: Conversion = {
  id: "cnv_000000000001",
  kind: "pdf",
  title: "The Sunless Citadel",
  mode: "ready",
  status: "running",
  step: "converting",
  done: 3,
  total: 40,
  steps: { index: 2, count: 5 },
  module_id: null,
  warnings: [],
  error: null,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:01:00Z",
};

function renderForm(
  source: NovelSource,
  { language = "en", tone = "classic", busy = null as Conversion | null, latestRevision = 3, onStarted = vi.fn() } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <NovelizeForm
          source={source}
          initial={defaultChoices(language, { tone, custom_tone: "" })}
          running={busy}
          latestRevision={latestRevision}
          onStarted={onStarted}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return onStarted;
}

const field = (name: string) => screen.getByLabelText(name) as HTMLInputElement | HTMLSelectElement;

describe("NovelizeForm", () => {
  it("offers the three lengths, recap first and chosen", () => {
    renderForm(CAMPAIGN);
    const lengths = screen.getAllByRole("radio").filter((r) => (r as HTMLInputElement).name === "novel-length");
    expect(lengths.map((r) => (r as HTMLInputElement).value)).toEqual(["recap", "short-story", "novella"]);
    expect((screen.getByLabelText("Recap") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByLabelText("Short story")).toBeTruthy();
    expect(screen.getByLabelText("Novella")).toBeTruthy();
  });

  it("defaults the tone to the campaign's, the language to the UI's, and all sessions", () => {
    renderForm(CAMPAIGN, { tone: "grimdark" });
    expect(field("Tone").value).toBe("grimdark");
    expect(field("Language").value).toBe("en");
    expect(field("Instructions").value).toBe("");
    expect((screen.getByLabelText("All sessions") as HTMLInputElement).checked).toBe(true);
    expect(screen.queryByLabelText("Revision")).toBeNull();
  });

  it("defaults the language to Dutch in a Dutch UI", () => {
    renderForm(CAMPAIGN, { language: "nl" });
    expect(field("Taal").value).toBe("nl");
  });

  it("gives a module classic, the latest revision, and no sessions", () => {
    renderForm(MODULE, { tone: "classic" });
    expect(field("Tone").value).toBe("classic");
    expect(field("Revision").value).toBe("");
    expect(screen.queryByLabelText("All sessions")).toBeNull();
  });

  it("posts the campaign's request, a range of sessions included", async () => {
    const fetchMock = stubFetch({
      "POST /api/novels": () => json(202, { id: "nov_000000000001", status: "writing" }),
    });
    const onStarted = renderForm(CAMPAIGN, { tone: "heroic" });
    fireEvent.click(screen.getByLabelText("Short story"));
    fireEvent.change(field("Instructions"), { target: { value: "Tell it from Ned's point of view." } });
    fireEvent.change(field("Language"), { target: { value: "nl" } });
    fireEvent.click(screen.getByLabelText("Sessions from"));
    fireEvent.change(field("First session"), { target: { value: "2" } });
    fireEvent.change(field("Last session"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Novelize" }));
    await waitFor(() => expect(onStarted).toHaveBeenCalled());
    expect(sent(fetchMock, "POST", "/api/novels")).toEqual([
      {
        source: "campaign",
        id: CAMPAIGN.id,
        length: "short-story",
        tone: "heroic",
        custom_tone: "",
        language: "nl",
        instructions: "Tell it from Ned's point of view.",
        sessions: [2, 4],
        revision: null,
      },
    ]);
  });

  it("posts a module's request with a custom tone and an older revision", async () => {
    const fetchMock = stubFetch({ "POST /api/novels": () => json(202, { id: "nov_000000000001" }) });
    renderForm(MODULE);
    fireEvent.change(field("Tone"), { target: { value: "custom" } });
    fireEvent.change(field("Your tone"), { target: { value: "Like a ballad" } });
    fireEvent.change(field("Revision"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Novelize" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/novels")).toHaveLength(1));
    expect(sent(fetchMock, "POST", "/api/novels")[0]).toMatchObject({
      source: "module",
      id: MODULE.id,
      length: "recap",
      tone: "custom",
      custom_tone: "Like a ballad",
      sessions: null,
      revision: 2,
    });
  });

  it("says a job is running and disables Novelize meanwhile", () => {
    renderForm(CAMPAIGN, { busy: running });
    expect(screen.getByRole("note").textContent).toContain("The Sunless Citadel");
    expect((screen.getByRole("button", { name: "Novelize" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows a refused start's message and hint", async () => {
    stubFetch({
      "POST /api/novels": () =>
        json(422, { error: "That range of sessions can't be written.", hint: "The campaign has 3 sessions." }),
    });
    renderForm(CAMPAIGN);
    fireEvent.click(screen.getByRole("button", { name: "Novelize" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("That range of sessions can't be written.");
    expect(alert.textContent).toContain("The campaign has 3 sessions.");
  });
});
