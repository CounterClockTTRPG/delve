import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "../play/testing";
import Possessions from "./Possessions";

afterEach(() => {
  vi.unstubAllGlobals();
});

const gull = {
  id: "pos_00000000000a",
  name: "The Gull",
  kind: "ship",
  owner: null,
  owner_id: null,
  location: "Hardby",
  value_gp: 3000,
  description: "A cog.",
  notes_md: "Smuggles for the cult.",
  inventory: [],
  stats: { mv: 12 },
  portrait: null,
};

function routes() {
  return {
    [`GET ${base}/possessions`]: () => json(200, [gull]),
    [`POST ${base}/possessions`]: (init: RequestInit | undefined) =>
      json(201, { ...gull, id: "pos_00000000000b", ...JSON.parse(String(init?.body)) }),
    [`PUT ${base}/possessions/${gull.id}`]: (init: RequestInit | undefined) => json(200, { ...gull, ...JSON.parse(String(init?.body)) }),
    [`DELETE ${base}/possessions/${gull.id}`]: () => new Response(null, { status: 204 }),
  };
}

describe("Possessions", () => {
  it("lists the possessions, the party's and the characters'", async () => {
    stubFetch(routes());
    renderWith(<Possessions campaignId={CAMPAIGN} />);
    const table = await screen.findByRole("table", { name: "Possessions" });
    expect(within(table).getByText("The Gull")).toBeTruthy();
    expect(within(table).getByText("Ship")).toBeTruthy();
    expect(within(table).getByText("The party")).toBeTruthy();
  });

  it("edits a possession, adds one and removes one after asking", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<Possessions campaignId={CAMPAIGN} />);
    const table = await screen.findByRole("table", { name: "Possessions" });
    fireEvent.click(within(table).getByRole("button", { name: "Edit The Gull" }));
    fireEvent.change(screen.getByLabelText("Where it is"), { target: { value: "Greyhawk" } });
    fireEvent.change(screen.getByLabelText(/DM notes/), { target: { value: "Clean now." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/possessions/${gull.id}`)).toHaveLength(1));
    expect(sent(fetchMock, "PUT", `${base}/possessions/${gull.id}`)[0]).toMatchObject({
      location: "Greyhawk",
      notes_md: "Clean now.",
      kind: "ship",
      owner: "",
    });

    fireEvent.click(screen.getByRole("button", { name: "Add a possession" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Bess" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/possessions`)).toEqual([{ name: "Bess", kind: "other" }]));

    fireEvent.click(within(table).getByRole("button", { name: "Delete The Gull" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/possessions/${gull.id}` && init?.method === "DELETE")).toBe(true),
    );
  });
});
