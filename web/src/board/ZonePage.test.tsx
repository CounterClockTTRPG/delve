import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch } from "../play/testing";
import { asAccount, asVisitor, author, post, renderBoard, rights, topic, topicPage, zone } from "./testing";

// `/board/:zoneId` (DEL-297): the topics, pinned first, with what is new; New topic for who may write, Log in to post
// for a visitor.

afterEach(() => vi.unstubAllGlobals());

const ZONE = "/api/board/zones/zon_00000000000a";

const topics = [
  topic({ id: "top_00000000000a", title: "Read this first", pinned: true, locked: true, posts: 3 }),
  topic({ id: "top_00000000000b", title: "Morale rolls", new: true, last_author: author({ display_name: "Raf" }) }),
];

describe("ZonePage", () => {
  it("lists the topics with their marks, starter, replies and last post", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${ZONE}`]: () => json(200, { zone: zone(), topics }) });
    renderBoard("/board/zon_00000000000a");
    expect(await screen.findByRole("heading", { level: 1, name: "The engine" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Where you are" }).textContent).toBe("Board › The engine");
    const [pinned, fresh] = screen.getAllByRole("listitem");
    expect(within(pinned).getByRole("img", { name: "Pinned" })).toBeTruthy();
    expect(within(pinned).getByRole("img", { name: "Locked" })).toBeTruthy();
    expect(within(pinned).getByText("Replies: 2")).toBeTruthy();
    expect(within(pinned).getByText("Started by Ana")).toBeTruthy();
    expect(within(pinned).queryByText("new")).toBeNull();
    expect(within(fresh).getByText("new")).toBeTruthy();
    expect(within(fresh).getByText(/^Last post by Raf, /)).toBeTruthy();
    expect(within(fresh).getByRole("link").getAttribute("href")).toBe("/board/zon_00000000000a/top_00000000000b");
  });

  it("starts a topic with its title and first post, and opens it", async () => {
    const made = topic({ id: "top_00000000000c", title: "Ideas" });
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      [`GET ${ZONE}`]: () => json(200, { zone: zone(), topics: [] }),
      [`POST ${ZONE}/topics`]: () => json(201, { topic: made, post: post("pst_00000000000a") }),
      "GET /api/board/topics/top_00000000000c": () => json(200, topicPage([post("pst_00000000000a")], { topic: made })),
    });
    renderBoard("/board/zon_00000000000a");
    fireEvent.click(await screen.findByRole("button", { name: "New topic" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: " Ideas " } });
    fireEvent.change(screen.getByRole("textbox", { name: "Your post" }), { target: { value: "Mine." } });
    fireEvent.click(screen.getByRole("button", { name: "Start the topic" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Ideas" })).toBeTruthy();
    const sent = fetchMock.mock.calls.find(([path, init]) => path === `${ZONE}/topics` && init?.method === "POST")!;
    expect(JSON.parse(String(sent[1]!.body))).toEqual({ title: "Ideas", text: "Mine." });
  });

  it("tells a visitor to log in to post where accounts write, and offers no New topic", async () => {
    stubFetch({ "GET /api/me": asVisitor, [`GET ${ZONE}`]: () => json(200, { zone: zone({ rights: rights({ write: false }) }), topics }) });
    renderBoard("/board/zon_00000000000a");
    expect((await screen.findByRole("link", { name: "Log in to post" })).getAttribute("href")).toBe("/login");
    expect(screen.queryByRole("button", { name: "New topic" })).toBeNull();
  });

  it("says so for a zone that isn't there", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${ZONE}`]: () => json(404, { error: "No such zone." }) });
    renderBoard("/board/zon_00000000000a");
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("This zone isn't here, or isn't open to you."));
  });

  it("offers Settings to who manages and People to who moderates a members zone", async () => {
    const mine = zone({ read: "members", write: "members", rights: rights({ manage: true, moderate: true }) });
    stubFetch({ "GET /api/me": asAccount(), [`GET ${ZONE}`]: () => json(200, { zone: mine, topics: [] }) });
    renderBoard("/board/zon_00000000000a");
    expect(await screen.findByRole("button", { name: "Settings" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "People" })).toBeTruthy();
  });

  it("offers neither to a plain reader", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${ZONE}`]: () => json(200, { zone: zone(), topics: [] }) });
    renderBoard("/board/zon_00000000000a");
    await screen.findByRole("heading", { level: 1, name: "The engine" });
    expect(screen.queryByRole("button", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("button", { name: "People" })).toBeNull();
  });
  it("with mail on, a new topic may be followed from the start", async () => {
    const made = topic({ id: "top_00000000000c", title: "Ideas", following: true });
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      "GET /api/mail/status": () => json(200, { enabled: true }),
      [`GET ${ZONE}`]: () => json(200, { zone: zone(), topics: [] }),
      [`POST ${ZONE}/topics`]: () => json(201, { topic: made, post: post("pst_00000000000a") }),
      "GET /api/board/topics/top_00000000000c": () => json(200, topicPage([post("pst_00000000000a")], { topic: made })),
    });
    renderBoard("/board/zon_00000000000a");
    fireEvent.click(await screen.findByRole("button", { name: "New topic" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Ideas" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Your post" }), { target: { value: "Mine." } });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Email me about replies" }));
    fireEvent.click(screen.getByRole("button", { name: "Start the topic" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Ideas" })).toBeTruthy();
    const sent = fetchMock.mock.calls.find(([path, init]) => path === `${ZONE}/topics` && init?.method === "POST")!;
    expect(JSON.parse(String(sent[1]!.body))).toEqual({ title: "Ideas", text: "Mine.", follow: true });
  });
});
