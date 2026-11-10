import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource, json, sent, stubFetch } from "../play/testing";
import { BOB, asAccount, asVisitor, author, post, renderBoard, rights, topic, topicPage, zone } from "./testing";

// A topic as a modern thread (DEL-297): who wrote each post above it, what the reader may do with it, and the reply
// box at the foot, or why there is none.

const scrollIntoView = Element.prototype.scrollIntoView;

afterEach(() => {
  vi.unstubAllGlobals();
  FakeEventSource.open = [];
  Element.prototype.scrollIntoView = scrollIntoView;
});

const TOPIC = "/api/board/topics/top_00000000000a";
const AT = "/board/zon_00000000000a/top_00000000000a";

const raf = author({ account_id: BOB, display_name: "Raf", avatar: { picture: "abc123abc123" }, badges: ["organiser", "moderator"] });

const thread = () => [
  post("pst_00000000000a", { mine: true }),
  post("pst_00000000000b", { author: raf, text: "Good idea.", edited_at: "2026-10-28T21:10:00Z" }),
  post("pst_00000000000c", { author: author({ account_id: "acc_00000000000c", display_name: "Cy" }), text: "", removed: "moderator" }),
];

function posts() {
  return screen.getAllByTestId("board-post");
}

describe("TopicPage", () => {
  it("shows each post's author above it, with badges, and a removed post without actions", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${TOPIC}`]: () => json(200, topicPage(thread())) });
    renderBoard(AT);
    await screen.findByRole("heading", { level: 1, name: "Could the DM roll morale in the open?" });
    const [first, second, removed] = posts();
    expect(within(first).getByText("Ana", { selector: "strong" })).toBeTruthy();
    expect(within(first).getByText("they flee").tagName).toBe("STRONG");
    expect(within(second).getByText("Raf", { selector: "strong" })).toBeTruthy();
    expect(within(second).getByText("organiser")).toBeTruthy();
    expect(within(second).getByText("moderator")).toBeTruthy();
    expect(within(second).getByText("edited")).toBeTruthy();
    // The uploaded face is the board's, by the post: never the profile's own route.
    expect(within(second).getByRole("img", { name: "Raf" }).getAttribute("src")).toBe("/api/board/posts/pst_00000000000b/avatar?v=abc123abc123");
    expect(within(removed).getByText("Removed by a moderator")).toBeTruthy();
    expect(within(removed).queryAllByRole("button")).toHaveLength(0);
  });

  it("names the owner by token and an author whose account is gone", async () => {
    const shown = [
      post("pst_00000000000a", { author: author({ account_id: null, display_name: "", avatar: null, colour: null }) }),
      post("pst_00000000000b", { author: author({ account_id: "acc_00000000000g", display_name: "", avatar: null, colour: null }) }),
    ];
    stubFetch({ "GET /api/me": asAccount(), [`GET ${TOPIC}`]: () => json(200, topicPage(shown)) });
    renderBoard(AT);
    const [owner, gone] = await waitFor(() => {
      const found = posts();
      expect(found).toHaveLength(2);
      return found;
    });
    expect(within(owner).getByText("Owner")).toBeTruthy();
    expect(within(gone).getByText("A former member")).toBeTruthy();
  });

  it("quotes a post into the reply box under its author", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${TOPIC}`]: () => json(200, topicPage(thread())) });
    renderBoard(AT);
    await screen.findAllByTestId("board-post");
    fireEvent.click(within(posts()[1]).getByRole("button", { name: "Quote" }));
    const box = screen.getByRole("textbox", { name: "Your reply" }) as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe("> **Raf wrote:**\n> Good idea.\n\n"));
  });

  it("sends a reply, and a picture picked with it once the post is made", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      [`GET ${TOPIC}`]: () => json(200, topicPage(thread(), { zone: zone({ pictures: true }) })),
      [`GET ${TOPIC}?page=1`]: () => json(200, topicPage(thread(), { zone: zone({ pictures: true }) })),
      [`POST ${TOPIC}/posts`]: () => json(201, { post: post("pst_00000000000d", { mine: true }) }),
      "POST /api/board/posts/pst_00000000000d/picture": () => json(200, { post: post("pst_00000000000d") }),
    });
    renderBoard(AT);
    const box = (await screen.findByRole("textbox", { name: "Your reply" })) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "  Agreed.  " } });
    const picture = new File(["png"], "map.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("Add a picture"), { target: { files: [picture] } });
    expect(screen.getByText("Picture: map.png")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Post" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.map(([path, init]) => `${init?.method ?? "GET"} ${path}`)).toContain(
        "POST /api/board/posts/pst_00000000000d/picture",
      ),
    );
    const sentReply = fetchMock.mock.calls.find(([path, init]) => path === `${TOPIC}/posts` && init?.method === "POST")!;
    expect(JSON.parse(String(sentReply[1]!.body))).toEqual({ text: "Agreed." });
    const sentPicture = fetchMock.mock.calls.find(([path]) => path === "/api/board/posts/pst_00000000000d/picture")!;
    expect(sentPicture[1]!.body).toBe(picture);
  });

  it("offers Edit and Delete on one's own post only, and moderation to moderators", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${TOPIC}`]: () => json(200, topicPage(thread())) });
    const { unmount } = renderBoard(AT);
    await screen.findAllByTestId("board-post");
    const [mine, theirs] = posts();
    expect(within(mine).getByRole("button", { name: "Edit" })).toBeTruthy();
    expect(within(mine).getByRole("button", { name: "Delete" })).toBeTruthy();
    expect(within(theirs).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(theirs).queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Lock" })).toBeNull();
    unmount();

    // An author who may no longer write there (a member removed, a player who left the table) may delete, not edit.
    stubFetch({
      "GET /api/me": asAccount(),
      [`GET ${TOPIC}`]: () => json(200, topicPage(thread(), { zone: zone({ rights: rights({ write: false }) }) })),
    });
    const outsider = renderBoard(AT);
    await screen.findAllByTestId("board-post");
    const [stillMine] = posts();
    expect(within(stillMine).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(stillMine).getByRole("button", { name: "Delete" })).toBeTruthy();
    outsider.unmount();

    const pictured = [post("pst_00000000000b", { author: raf, picture: { width: 300, height: 200 } })];
    stubFetch({
      "GET /api/me": asAccount(),
      [`GET ${TOPIC}`]: () => json(200, topicPage(pictured, { zone: zone({ rights: rights({ moderate: true }) }) })),
    });
    renderBoard(AT);
    const [moderated] = await screen.findAllByTestId("board-post");
    expect(within(moderated).queryByRole("button", { name: "Edit" })).toBeNull();
    expect(within(moderated).getByRole("button", { name: "Delete" })).toBeTruthy();
    expect(within(moderated).getByRole("button", { name: "Take picture down" })).toBeTruthy();
    expect(within(moderated).getByRole("button", { name: "Enlarge Raf's picture" })).toBeTruthy();
    for (const name of ["Pin", "Lock", "Delete topic"]) expect(screen.getByRole("button", { name })).toBeTruthy();
  });

  it("says a locked topic is locked instead of a reply box, unless the reader moderates", async () => {
    const locked = topic({ locked: true, posts: 1 });
    stubFetch({ "GET /api/me": asAccount(), [`GET ${TOPIC}`]: () => json(200, topicPage([post("pst_00000000000a")], { topic: locked })) });
    const { unmount } = renderBoard(AT);
    expect(await screen.findByTestId("board-locked")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Quote" })).toBeNull();
    unmount();

    stubFetch({
      "GET /api/me": asAccount(),
      [`GET ${TOPIC}`]: () =>
        json(200, topicPage([post("pst_00000000000a")], { topic: locked, zone: zone({ rights: rights({ moderate: true }) }) })),
    });
    renderBoard(AT);
    expect(await screen.findByRole("textbox", { name: "Your reply" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Unlock" })).toBeTruthy();
  });

  it("tells a visitor to log in instead of a reply box", async () => {
    stubFetch({
      "GET /api/me": asVisitor,
      [`GET ${TOPIC}`]: () => json(200, topicPage(thread(), { zone: zone({ rights: rights({ write: false }) }) })),
    });
    renderBoard(AT);
    await screen.findAllByTestId("board-post");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Quote" })).toBeNull();
    const links = screen.getAllByRole("link", { name: /Log in/ });
    expect(links.map((link) => link.textContent)).toEqual(["Log in", "Log in to post"]);
  });

  it("tells a visitor to log in only where accounts write", async () => {
    stubFetch({
      "GET /api/me": asVisitor,
      [`GET ${TOPIC}`]: () =>
        json(200, topicPage(thread(), { zone: zone({ read: "everybody", write: "members", rights: rights({ write: false }) }) })),
    });
    renderBoard(AT);
    await screen.findAllByTestId("board-post");
    expect(screen.getAllByRole("link", { name: /Log in/ }).map((link) => link.textContent)).toEqual(["Log in"]);
  });

  it("opens at the page the server picks, keeps it, and reads again on a board event", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    const second = [post("pst_00000000000d"), post("pst_00000000000e")];
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      [`GET ${TOPIC}`]: () => json(200, topicPage(second, { page: 2, pages: 2, first_unread_page: 2, first_unread_post: "pst_00000000000e" })),
      [`GET ${TOPIC}?page=2`]: () => json(200, topicPage(second, { page: 2, pages: 2, first_unread_page: 2 })),
    });
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    renderBoard(AT);
    // Above the posts and below them.
    expect(await screen.findAllByText("Page 2 of 2")).toHaveLength(2);
    await waitFor(() => expect(scrolled).toHaveBeenCalled());
    expect((scrolled.mock.contexts[0] as Element).id).toBe("post-pst_00000000000e");
    FakeEventSource.emit("board", { zone_id: "zon_00000000000a", topic_id: "top_00000000000a" });
    await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => path === `${TOPIC}?page=2`)).toHaveLength(1));
    expect(fetchMock.mock.calls.filter(([path]) => path === TOPIC)).toHaveLength(1);
  });
  it("with mail on, the reply box offers Email me about replies and sends it as follow", async () => {
    const page = () => json(200, topicPage(thread()));
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      "GET /api/mail/status": () => json(200, { enabled: true }),
      [`GET ${TOPIC}`]: page,
      [`GET ${TOPIC}?page=1`]: page,
      [`POST ${TOPIC}/posts`]: () => json(201, { post: post("pst_00000000000d", { mine: true }) }),
    });
    renderBoard(AT);
    const box = (await screen.findByRole("textbox", { name: "Your reply" })) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "Agreed." } });
    fireEvent.click(await screen.findByRole("checkbox", { name: "Email me about replies" }));
    fireEvent.click(screen.getByRole("button", { name: "Post" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${TOPIC}/posts`)).toEqual([{ text: "Agreed.", follow: true }]));
  });

  it("offers Follow and Stop following to a signed-in reader while mail is on", async () => {
    let following = false;
    const page = () => json(200, topicPage(thread(), { topic: topic({ following }) }));
    const fetchMock = stubFetch({
      "GET /api/me": asAccount(),
      "GET /api/mail/status": () => json(200, { enabled: true }),
      [`GET ${TOPIC}`]: page,
      [`GET ${TOPIC}?page=1`]: page,
      [`PUT ${TOPIC}/follow`]: () => ((following = true), json(200, { following })),
      [`DELETE ${TOPIC}/follow`]: () => ((following = false), json(200, { following })),
    });
    renderBoard(AT);
    fireEvent.click(await screen.findByRole("button", { name: "Follow" }));
    const stop = await screen.findByRole("button", { name: "Stop following" });
    // Following already, the reply box doesn't ask again.
    expect(screen.queryByRole("checkbox", { name: "Email me about replies" })).toBeNull();
    fireEvent.click(stop);
    expect(await screen.findByRole("button", { name: "Follow" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Email me about replies" })).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([path]) => path === `${TOPIC}/follow`).map(([, init]) => init?.method)).toEqual(["PUT", "DELETE"]);
  });

  it("offers neither without mail, nor Follow to a visitor", async () => {
    stubFetch({ "GET /api/me": asAccount(), [`GET ${TOPIC}`]: () => json(200, topicPage(thread())) });
    const { unmount } = renderBoard(AT);
    await screen.findByRole("textbox", { name: "Your reply" });
    expect(screen.queryByRole("checkbox", { name: "Email me about replies" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Follow" })).toBeNull();
    unmount();
    stubFetch({
      "GET /api/me": asVisitor,
      "GET /api/mail/status": () => json(200, { enabled: true }),
      [`GET ${TOPIC}`]: () => json(200, topicPage(thread(), { zone: zone({ read: "everybody", rights: rights({ write: false }) }) })),
    });
    renderBoard(AT);
    await screen.findAllByTestId("board-post");
    expect(screen.queryByRole("button", { name: "Follow" })).toBeNull();
  });
});
