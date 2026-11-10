import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "../play/testing";
import Quests from "./Quests";

afterEach(() => {
  vi.unstubAllGlobals();
});

const relic = {
  id: "relic",
  title: "Find the relic",
  giver: "the abbot",
  scope: "local",
  stakes: "The ward fails.",
  status: "available",
  known: false,
  started_day: null,
  ended_day: null,
  related: [],
  log: [{ day: 1, text: "The abbot lied.", known: false }],
  notes_md: "The relic is fake.",
};

function routes() {
  return {
    [`GET ${base}/quests`]: () => json(200, [relic]),
    [`PUT ${base}/quests/relic`]: (init: RequestInit | undefined) => json(200, { ...relic, ...JSON.parse(String(init?.body)) }),
    [`PUT ${base}/quests/the-coup`]: (init: RequestInit | undefined) =>
      json(200, { ...relic, id: "the-coup", ...JSON.parse(String(init?.body)) }),
    [`DELETE ${base}/quests/relic`]: () => new Response(null, { status: 204 }),
  };
}

describe("Quests", () => {
  it("lists the quests, whether the characters know them, and marks the DM-only fields", async () => {
    stubFetch(routes());
    renderWith(<Quests campaignId={CAMPAIGN} />);
    const table = await screen.findByRole("table", { name: "Quests" });
    expect(within(table).getByText("Find the relic")).toBeTruthy();
    expect(within(table).getByText("Available")).toBeTruthy();
    expect(within(table).getByText("Not known")).toBeTruthy();
  });

  it("edits a quest, its notes too, adds one and deletes one", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<Quests campaignId={CAMPAIGN} />);
    const table = await screen.findByRole("table", { name: "Quests" });
    fireEvent.click(within(table).getByRole("button", { name: "Edit Find the relic" }));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "active" } });
    fireEvent.click(screen.getByLabelText("The characters know it"));
    fireEvent.click(screen.getByLabelText("The characters know note 1"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/quests/relic`)).toHaveLength(1));
    expect(sent(fetchMock, "PUT", `${base}/quests/relic`)[0]).toMatchObject({
      status: "active",
      known: true,
      log: [{ day: 1, text: "The abbot lied.", known: true }],
      notes_md: "The relic is fake.",
    });

    fireEvent.click(screen.getByRole("button", { name: "Add a quest" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "The coup" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/quests/the-coup`)).toEqual([{ title: "The coup" }]));

    fireEvent.click(within(table).getByRole("button", { name: "Delete Find the relic" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/quests/relic` && init?.method === "DELETE")).toBe(true),
    );
  });
});
