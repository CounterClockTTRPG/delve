import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "../play/testing";
import Factions from "./Factions";

afterEach(() => {
  vi.unstubAllGlobals();
});

const watch = {
  id: "watch",
  name: "The Watch",
  alignment: "LN",
  goals: "Order",
  scope: "local",
  known: true,
  strength: 80,
  reputation: 30,
  standing: "Friendly",
  notes_md: "The captain is bribed.",
};
const clock = {
  id: 7,
  label: "The eye wakes",
  kind: "countdown",
  faction: "watch",
  days_remaining: 3,
  segments: null,
  filled: null,
  on_complete: "The eye opens.",
  started_day: 1,
  done_day: null,
};

function routes() {
  const echo = (init: RequestInit | undefined) => json(200, { ...watch, ...JSON.parse(String(init?.body)) });
  return {
    [`GET ${base}/factions`]: () => json(200, [watch]),
    [`GET ${base}/clocks`]: () => json(200, [clock]),
    [`PUT ${base}/factions/watch`]: echo,
    [`PUT ${base}/factions/the-guild`]: echo,
    [`DELETE ${base}/factions/watch`]: () => new Response(null, { status: 204 }),
    [`POST ${base}/clocks`]: (init: RequestInit | undefined) => json(201, { ...clock, id: 8, ...JSON.parse(String(init?.body)) }),
    [`PUT ${base}/clocks/7`]: (init: RequestInit | undefined) => json(200, { ...clock, ...JSON.parse(String(init?.body)) }),
    [`DELETE ${base}/clocks/7`]: () => new Response(null, { status: 204 }),
  };
}

describe("Factions", () => {
  it("lists the factions and clocks, the DM-only fields marked", async () => {
    stubFetch(routes());
    renderWith(<Factions campaignId={CAMPAIGN} />);
    const table = await screen.findByRole("table", { name: "Factions" });
    expect(within(table).getByText("The Watch")).toBeTruthy();
    expect(within(table).getByText("Friendly")).toBeTruthy();
    expect(within(table).getAllByText("DM only").length).toBeGreaterThan(0);
    const clocks = screen.getByRole("table", { name: "Clocks" });
    expect(within(clocks).getByText("The eye wakes")).toBeTruthy();
    expect(within(clocks).getByText("3 days left")).toBeTruthy();
  });

  it("edits a faction, adds one by name and deletes one after asking", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<Factions campaignId={CAMPAIGN} />);
    const table = await screen.findByRole("table", { name: "Factions" });
    fireEvent.click(within(table).getByRole("button", { name: "Edit The Watch" }));
    fireEvent.change(screen.getByLabelText(/Reputation/), { target: { value: "-40" } });
    fireEvent.change(screen.getByLabelText(/DM notes/), { target: { value: "Bribed twice." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/factions/watch`)).toHaveLength(1));
    const [put] = sent(fetchMock, "PUT", `${base}/factions/watch`) as Record<string, unknown>[];
    expect(put).toMatchObject({ name: "The Watch", reputation: -40, notes_md: "Bribed twice.", known: true });

    fireEvent.click(screen.getByRole("button", { name: "Add a faction" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "The Guild" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/factions/the-guild`)).toEqual([{ name: "The Guild" }]));

    fireEvent.click(within(table).getByRole("button", { name: "Delete The Watch" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/factions/watch` && init?.method === "DELETE")).toBe(true),
    );
  });

  it("adds, edits and deletes clocks", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<Factions campaignId={CAMPAIGN} />);
    const clocks = await screen.findByRole("table", { name: "Clocks" });
    fireEvent.click(within(clocks).getByRole("button", { name: "Edit The eye wakes" }));
    fireEvent.change(screen.getByLabelText("Days left"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/clocks/7`)).toHaveLength(1));
    expect(sent(fetchMock, "PUT", `${base}/clocks/7`)[0]).toMatchObject({ days_remaining: 5, kind: "countdown" });

    fireEvent.click(screen.getByRole("button", { name: "Add a clock" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "The ritual" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/clocks`)).toEqual([{ label: "The ritual", kind: "progress", segments: 4 }]),
    );

    fireEvent.click(within(clocks).getByRole("button", { name: "Delete The eye wakes" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/clocks/7` && init?.method === "DELETE")).toBe(true),
    );
  });
});
