import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, sent, stubFetch } from "../play/testing";
import { asAccount, asVisitor, author, boardZone, renderBoard, rights } from "./testing";

// `/board` (DEL-297): the zones in order, with who reads and writes there, what was written last and what is new.

afterEach(() => vi.unstubAllGlobals());

const zones = [
  boardZone({
    id: "zon_00000000000a",
    name: "The engine",
    topics: 4,
    new_topics: 2,
    latest: { topic_id: "top_00000000000a", title: "Morale in the open?", at: new Date().toISOString(), author: author() },
  }),
  boardZone({ id: "zon_00000000000b", name: "Our table", description: "", read: "table", write: "table" }),
];

describe("BoardIndex", () => {
  it("marks a zone's new topics on the board", async () => {
    stubFetch({ "GET /api/me": asAccount(), "GET /api/board": () => json(200, { zones, may_create: false, signed_in: true }) });
    renderBoard("/board");
    const items = await screen.findAllByRole("listitem");
    expect(items.map((item) => within(item).getAllByRole("link")[0].textContent)).toEqual(["The engine", "Our table"]);
    expect(within(items[0]).getAllByRole("link")[0].getAttribute("href")).toBe("/board/zon_00000000000a");
    expect(within(items[0]).getByText("Anyone can read, accounts post")).toBeTruthy();
    expect(within(items[0]).getByText("Topics: 4")).toBeTruthy();
    expect(within(items[0]).getByText("2 new")).toBeTruthy();
    const latest = within(items[0]).getByRole("link", { name: "Morale in the open?" });
    expect(latest.getAttribute("href")).toBe("/board/zon_00000000000a/top_00000000000a");
    expect(within(items[0]).getByText(/^Ana, /)).toBeTruthy();
    expect(within(items[1]).getByText("This table only")).toBeTruthy();
    expect(within(items[1]).getByText("No topics here yet.")).toBeTruthy();
    expect(within(items[1]).queryByText(/^Topics:/)).toBeNull();
    expect(within(items[1]).queryByText(/new/)).toBeNull();
    expect(screen.getByRole("link", { name: "Back to Delve" }).getAttribute("href")).toBe("/home");
  });

  it("offers a visitor Log in, with the wordmark to the front page, in the language asked", async () => {
    stubFetch({ "GET /api/me": asVisitor, "GET /api/board": () => json(200, { zones: [], may_create: false, signed_in: false }) });
    renderBoard("/board?lang=nl");
    expect(await screen.findByText("Er zijn nog geen zones op het forum.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Inloggen" }).getAttribute("href")).toBe("/login");
    expect(screen.getAllByRole("link", { name: "Delve" })[0].getAttribute("href")).toBe("/");
  });

  it("lets an organiser make a zone and move one down", async () => {
    const wide = zones.map((z) => ({ ...z, rights: rights({ manage: true, manage_wide: true }) }));
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      "GET /api/board": () => json(200, { zones: wide, may_create: true, signed_in: true }),
      "GET /api/campaigns": () => json(200, []),
      "PUT /api/board/order": () => json(200, { zones: [] }),
    });
    renderBoard("/board");
    fireEvent.click(await screen.findByRole("button", { name: "New zone" }));
    expect(await screen.findByRole("dialog", { name: "New zone" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByRole("button", { name: /^Move / })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Arrange zones" }));
    expect(screen.getByRole("button", { name: "Move The engine up" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Move The engine down" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", "/api/board/order")).toEqual([{ zone_ids: ["zon_00000000000b", "zon_00000000000a"] }]));
  });

  it("offers no New zone or moving to who may not", async () => {
    stubFetch({ "GET /api/me": asAccount(), "GET /api/board": () => json(200, { zones, may_create: false, signed_in: true }) });
    renderBoard("/board");
    await screen.findByText("The engine");
    expect(screen.queryByRole("button", { name: "New zone" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Move / })).toBeNull();
    expect(screen.queryByRole("button", { name: "Arrange zones" })).toBeNull();
  });
});
