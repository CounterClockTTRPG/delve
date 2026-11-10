import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, sent, stubFetch, type Handler } from "../play/testing";
import type { Proposal } from "./api";
import { page, renderArea, settingInfo } from "./testing";

const base = "/api/settings/oerth";
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof stubFetch>;
let pending: Proposal[];

const proposal = (id: number, kind: Proposal["kind"], extra: Partial<Proposal> = {}): Proposal => ({
  id,
  campaign_id: "cmp_00000000000a",
  campaign_title: "The Crypt",
  kind,
  title: "",
  text: "",
  mode: "append",
  page_kind: "",
  category: "",
  dm_only: false,
  status: "pending",
  created_at: `2026-10-19T10:0${id}:00Z`,
  decided_at: null,
  ...extra,
});

beforeEach(() => {
  pending = [
    proposal(1, "fact", { text: "The ferry at Hardby sank.", category: "events" }),
    proposal(2, "edit", { title: "Hardby", text: "The Despotrix fell ill.", dm_only: true }),
    proposal(3, "page", { title: "Hob Hill", text: "A village near [[Hardby]].", page_kind: "settlements" }),
  ];
  routes = {
    [`GET ${base}`]: () => json(200, settingInfo("oerth", "Oerth", { counts: { pages: 0, facts: 0, proposals: pending.length } })),
    [`GET ${base}/proposals?status=pending`]: () => json(200, pending),
  };
  fetchMock = stubFetch(routes);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const rowOf = async (text: string) => (await screen.findByText(text)).closest("li")!;

describe("ProposalsTab", () => {
  it("lists the pending proposals newest first, with their kind, campaign, text and DM only", async () => {
    renderArea("/settings/oerth?tab=proposals");
    expect(await screen.findByRole("tab", { name: "Proposals 3" })).toBeTruthy();
    await screen.findByText("The ferry at Hardby sank.");
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => within(r).getByText(/^(New page|Change to Hardby|Fact)$/).textContent)).toEqual([
      "New page",
      "Change to Hardby",
      "Fact",
    ]);
    expect(within(rows[0]).getByText("Hob Hill")).toBeTruthy();
    expect(within(rows[0]).getByRole("link", { name: "Hardby" }).getAttribute("href")).toBe("/settings/oerth/pages/Hardby");
    expect(within(rows[0]).getByRole("link", { name: "The Crypt" }).getAttribute("href")).toBe("/campaigns/cmp_00000000000a");
    expect(within(rows[1]).getByText("DM only")).toBeTruthy();
    expect(within(rows[2]).queryByText("DM only")).toBeNull();
  });

  it("Accept posts accept and the row goes", async () => {
    routes[`POST ${base}/proposals/1/accept`] = () => {
      const done = { ...pending[0], status: "accepted" };
      pending = pending.slice(1);
      return json(200, { proposal: done, fact: { id: 7, text: done.text, category: "events", dm_only: false, created_at: "" } });
    };
    renderArea("/settings/oerth?tab=proposals");
    const row = await rowOf("The ferry at Hardby sank.");
    fireEvent.click(within(row).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(screen.queryByText("The ferry at Hardby sank.")).toBeNull());
    expect(fetchMock.mock.calls.filter(([p, init]) => p === `${base}/proposals/1/accept` && init?.method === "POST")).toHaveLength(1);
    expect(await screen.findByRole("tab", { name: "Proposals 2" })).toBeTruthy();
  });

  it("Edit then Accept sends the edited text first", async () => {
    const order: string[] = [];
    routes[`PUT ${base}/proposals/3`] = (init) => {
      order.push("edit");
      pending = pending.map((p) => (p.id === 3 ? { ...p, ...JSON.parse(String(init?.body)) } : p));
      return json(200, pending.find((p) => p.id === 3));
    };
    routes[`POST ${base}/proposals/3/accept`] = () => {
      order.push("accept");
      const done = { ...pending.find((p) => p.id === 3)!, status: "accepted" };
      pending = pending.filter((p) => p.id !== 3);
      return json(200, { proposal: done, page: page(done.title, { origin: "addition" }) });
    };
    renderArea("/settings/oerth?tab=proposals");
    const row = await rowOf("Hob Hill");
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(row).getByLabelText("Title"), { target: { value: "Hob's Hill" } });
    fireEvent.change(within(row).getByLabelText("Text"), { target: { value: "A hamlet near Hardby." } });
    fireEvent.click(within(row).getByLabelText("DM only"));
    fireEvent.click(within(row).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(order).toEqual(["edit", "accept"]));
    expect(sent(fetchMock, "PUT", `${base}/proposals/3`)).toEqual([
      { title: "Hob's Hill", text: "A hamlet near Hardby.", dm_only: true },
    ]);
    await waitFor(() => expect(screen.queryByText("Hob's Hill")).toBeNull());
  });

  it("Edit of a fact offers its category, and Save keeps the proposal pending", async () => {
    routes[`PUT ${base}/proposals/1`] = (init) => {
      pending = pending.map((p) => (p.id === 1 ? { ...p, ...JSON.parse(String(init?.body)) } : p));
      return json(200, pending.find((p) => p.id === 1));
    };
    renderArea("/settings/oerth?tab=proposals");
    const row = await rowOf("The ferry at Hardby sank.");
    fireEvent.click(within(row).getByRole("button", { name: "Edit" }));
    expect(within(row).queryByLabelText("Title")).toBeNull();
    fireEvent.change(within(row).getByLabelText("Category"), { target: { value: "disasters" } });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("disasters")).toBeTruthy();
    expect(sent(fetchMock, "PUT", `${base}/proposals/1`)).toEqual([
      { text: "The ferry at Hardby sank.", category: "disasters", dm_only: false },
    ]);
    expect(fetchMock.mock.calls.some(([p]) => String(p).endsWith("/accept"))).toBe(false);
  });

  it("a 409 shows the server's message and keeps the row", async () => {
    routes[`POST ${base}/proposals/3/accept`] = () =>
      json(409, { error: "There is a page titled Hob Hill already: edit the proposal's title, or reject it." });
    renderArea("/settings/oerth?tab=proposals");
    const row = await rowOf("Hob Hill");
    fireEvent.click(within(row).getByRole("button", { name: "Accept" }));
    expect(
      (await within(row).findByRole("alert")).textContent,
    ).toContain("There is a page titled Hob Hill already: edit the proposal's title, or reject it.");
    expect(screen.getByText("Hob Hill")).toBeTruthy();
  });

  it("Reject asks first", async () => {
    routes[`POST ${base}/proposals/2/reject`] = () => {
      const done = { ...pending[1], status: "rejected" };
      pending = pending.filter((p) => p.id !== 2);
      return json(200, done);
    };
    renderArea("/settings/oerth?tab=proposals");
    const row = await rowOf("The Despotrix fell ill.");
    fireEvent.click(within(row).getByRole("button", { name: "Reject" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock.mock.calls.some(([p]) => String(p).endsWith("/reject"))).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(screen.queryByText("The Despotrix fell ill.")).toBeNull());
    expect(fetchMock.mock.calls.filter(([p, init]) => p === `${base}/proposals/2/reject` && init?.method === "POST")).toHaveLength(1);
  });

  it("says when nothing is pending", async () => {
    pending = [];
    renderArea("/settings/oerth?tab=proposals");
    expect(await screen.findByText("No proposals wait for you.")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Proposals" })).toBeTruthy();
  });
});
