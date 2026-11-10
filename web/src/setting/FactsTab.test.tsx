import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, sent, stubFetch, type Handler } from "../play/testing";
import type { SettingFact } from "./api";
import { renderArea, settingInfo } from "./testing";

const base = "/api/settings/oerth";
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof stubFetch>;
let own: SettingFact[];

const fact = (id: number, text: string, extra: Partial<SettingFact> = {}): SettingFact => ({
  id,
  text,
  category: "",
  dm_only: false,
  created_at: "2026-10-19T10:00:00Z",
  ...extra,
});

beforeEach(() => {
  own = [fact(1, "The Wild Coast has a new lord.", { category: "politics" }), fact(2, "Iuz is behind it.", { dm_only: true })];
  routes = {
    [`GET ${base}`]: () => json(200, settingInfo("oerth", "Oerth")),
    [`GET ${base}/facts`]: () =>
      json(200, {
        shipped: [
          { id: 10, text: "The Free City is ruled by its Directing Oligarchy.", category: "politics" },
          { id: 11, text: "Common Year counts from the Twin Cataclysms.", category: "history" },
        ],
        own,
      }),
  };
  fetchMock = stubFetch(routes);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("FactsTab", () => {
  it("lists the install's facts, the DM-only ones marked, and the book's read-only by category", async () => {
    renderArea("/settings/oerth?tab=facts");
    const mine = (await screen.findByText("Iuz is behind it.")).closest("li")!;
    expect(within(mine).getByText("DM only")).toBeTruthy();
    expect(within(screen.getByText("The Wild Coast has a new lord.").closest("li")!).queryByText("DM only")).toBeNull();
    const book = screen.getByRole("region", { name: "From the book" });
    expect(within(book).getByRole("heading", { name: "politics" })).toBeTruthy();
    expect(within(book).getByRole("heading", { name: "history" })).toBeTruthy();
    const shipped = within(book).getByText("The Free City is ruled by its Directing Oligarchy.").closest("li")!;
    expect(within(shipped).queryByRole("button")).toBeNull();
  });

  it("Add posts the text, the category and DM only", async () => {
    routes[`POST ${base}/facts`] = (init) => {
      const body = JSON.parse(String(init?.body));
      own = [...own, fact(3, body.text, body)];
      return json(201, own[own.length - 1]);
    };
    renderArea("/settings/oerth?tab=facts");
    const form = (await screen.findByRole("button", { name: "Add the fact" })).closest("form")!;
    fireEvent.change(within(form).getByLabelText("Fact"), { target: { value: "Hardby's Despotrix is ill." } });
    fireEvent.change(within(form).getByLabelText("Category"), { target: { value: "people" } });
    fireEvent.click(within(form).getByLabelText("DM only"));
    fireEvent.click(within(form).getByRole("button", { name: "Add the fact" }));
    expect(await screen.findByText("Hardby's Despotrix is ill.")).toBeTruthy();
    expect(sent(fetchMock, "POST", `${base}/facts`)).toEqual([{ text: "Hardby's Despotrix is ill.", category: "people", dm_only: true }]);
  });

  it("Edit saves the changed fact", async () => {
    routes[`PUT ${base}/facts/1`] = (init) => {
      own = [{ ...own[0], ...JSON.parse(String(init?.body)) }, own[1]];
      return json(200, own[0]);
    };
    renderArea("/settings/oerth?tab=facts");
    const row = (await screen.findByText("The Wild Coast has a new lord.")).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(row).getByLabelText("Fact"), { target: { value: "The Wild Coast has two lords." } });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("The Wild Coast has two lords.")).toBeTruthy();
    expect(sent(fetchMock, "PUT", `${base}/facts/1`)).toEqual([
      { text: "The Wild Coast has two lords.", category: "politics", dm_only: false },
    ]);
  });

  it("Delete asks first", async () => {
    routes[`DELETE ${base}/facts/2`] = () => {
      own = own.filter((f) => f.id !== 2);
      return new Response(null, { status: 204 });
    };
    renderArea("/settings/oerth?tab=facts");
    const row = (await screen.findByText("Iuz is behind it.")).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByText("Iuz is behind it.")).toBeNull());
    expect(fetchMock.mock.calls.filter(([p, init]) => p === `${base}/facts/2` && init?.method === "DELETE")).toHaveLength(1);
  });

  it("says when the install has no facts of its own", async () => {
    own = [];
    renderArea("/settings/oerth?tab=facts");
    expect(await screen.findByText("No facts added on this install yet.")).toBeTruthy();
  });
});
