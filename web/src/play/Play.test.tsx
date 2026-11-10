import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { portraitSvg } from "../components/Portrait";
import Play from "../routes/Play";
import type { RunningBeat, TableSession } from "./api";
import {
  CAMPAIGN,
  FakeEventSource,
  base,
  character,
  entry,
  hostSeat,
  json,
  me,
  playRoutes,
  playState,
  renderWith,
  seat,
  sent,
  stubFetch,
  worldRoutes,
} from "./testing";

vi.mock("qrcode", () => ({ default: { toCanvas: vi.fn(async () => undefined) } }));

const BEAT = "beat_000000000001";

beforeEach(() => {
  FakeEventSource.open = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const ana = seat("seat_00000000000a", "Ana", { language: "nl", characters: ["chr_00000000000a"] });
const cy = seat("seat_00000000000c", "Cy", { role: "observer" });

/** The phone's media query, answered by `phone`. */
function stubScreen(phone: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: phone && query.includes("max-width"),
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

function actButton() {
  return screen.getByTestId("act") as HTMLButtonElement;
}

describe("the play screen", () => {
  it("picks a campaign from a list of 20 a page, the page in the address", async () => {
    const campaigns = Array.from({ length: 21 }, (_, i) => ({ id: `cmp_${i}`, name: `Group ${i + 1}`, module_id: "mod_x" }));
    stubFetch({ "GET /api/campaigns": () => json(200, campaigns) });
    renderWith(<Play />, "/play?page=2");
    const only = await screen.findByRole("link", { name: "Group 21" });
    expect(only.getAttribute("href")).toBe("/play/cmp_20");
    expect(screen.queryByRole("link", { name: "Group 1" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Campaigns pages" }).textContent).toContain("21–21 of 21");
  });

  it("marks the complete campaigns, which still open for play (DEL-244)", async () => {
    const campaigns = [
      { id: "cmp_done", name: "The Finished Run", module_id: "mod_x", status: "complete" },
      { id: "cmp_live", name: "The Running One", module_id: "mod_x", status: "in_progress" },
    ];
    stubFetch({ "GET /api/campaigns": () => json(200, campaigns) });
    renderWith(<Play />, "/play");
    const done = await screen.findByRole("link", { name: "The Finished Run" });
    expect(done.getAttribute("href")).toBe("/play/cmp_done");
    expect(within(done.closest("li")!).getByText("Complete")).toBeTruthy();
    const live = screen.getByRole("link", { name: "The Running One" });
    expect(within(live.closest("li")!).queryByText("Complete")).toBeNull();
  });

  it("an unknown campaign is a plain not-found page, with no story or header", async () => {
    stubFetch({ [`GET ${base}/play/state`]: () => json(404, { error: "No such campaign." }) });
    renderWith(<Play />);
    expect(await screen.findByText("There is no such campaign.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Pick a campaign to play" }).getAttribute("href")).toBe("/play");
    expect(screen.queryByTestId("story")).toBeNull();
    expect(document.querySelector(".play-head")).toBeNull();
    expect(screen.queryByTestId("act")).toBeNull();
  });

  it("the empty story shows the book's ink drawing, not the campaign's banner, which is too big there", async () => {
    const routes = playRoutes();
    routes[`GET ${base}/play/state`] = () => json(200, playState({ banner: "img_00000000000b" }));
    stubFetch(routes);
    renderWith(<Play />);
    const story = await screen.findByTestId("story");
    await screen.findByText("Say what your character does in the box below, and the DM takes it from there.");
    expect(story.querySelector(".story-empty-art")).not.toBeNull();
    expect(within(story).queryByRole("img")).toBeNull();
  });

  it("leaves table talk and Share out while the seat is alone at the table, and shows them once someone sits down (DEL-232)", async () => {
    let seats = [hostSeat];
    const answer = { ...entry(7, "answer", { text: "A small, dog-like humanoid." }, ""), beat_id: null, audience: { seats: [hostSeat.id] } };
    const ask = { ...entry(6, "ask", { text: "What's a kobold?" }, ""), beat_id: null, audience: { seats: [hostSeat.id] } };
    const routes = playRoutes(playState(), [ask, answer]);
    routes[`GET ${base}/seats`] = () => json(200, seats);
    stubFetch(routes);
    renderWith(<Play />);

    await within(screen.getByTestId("story")).findByText(/dog-like/);
    expect(screen.queryByTestId("talk-box")).toBeNull();
    expect(screen.queryByRole("button", { name: "Share with the table" })).toBeNull();

    seats = [hostSeat, seat("seat_00000000000b", "Bo", { role: "observer" })];
    FakeEventSource.emit("seats", { campaign_id: CAMPAIGN });
    expect(await screen.findByTestId("talk-box")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Share with the table" })).toBeTruthy();
  });

  it("says how long to wait when the seat talks too fast (DEL-154)", async () => {
    const routes = playRoutes(playState(), [], { seats: [hostSeat, seat("seat_00000000000b", "Bo")] });
    const slow = "You're talking fast: say it again in 12 seconds.";
    routes[`POST ${base}/talk`] = () => json(429, { error: slow });
    stubFetch(routes);
    renderWith(<Play />);

    const talkBox = await screen.findByTestId("talk-box");
    const box = within(talkBox).getByRole("textbox");
    fireEvent.change(box, { target: { value: "Hello?" } });
    fireEvent.click(within(talkBox).getByTestId("talk"));
    expect((await within(talkBox).findByRole("alert")).textContent).toBe(slow);
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe("Hello?"), { timeout: 2000 });
  });

  it("gives a refused question back to the box, still a question", async () => {
    const routes = playRoutes();
    routes[`POST ${base}/ask`] = () => json(429, { error: "You're asking fast: ask again in 30 seconds." });
    stubFetch(routes);
    renderWith(<Play />);

    const composer = await screen.findByTestId("composer");
    const box = within(composer).getByRole("textbox");
    fireEvent.click(within(composer).getByTestId("mode-ask"));
    fireEvent.change(box, { target: { value: "Is the door trapped?" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe("Is the door trapped?"));
    expect(within(composer).getByTestId("mode-ask").getAttribute("aria-pressed")).toBe("true");
  });

  it("Act posts and disables until the beat is done", async () => {
    // The server's side: the beat runs from the Act until it is done.
    const running = { id: BEAT, status: "running", elapsed_s: 0 } as const;
    let beat: typeof running | null = null;
    const routes = playRoutes();
    routes[`GET ${base}/play/state`] = () => json(200, playState({ beat }));
    routes[`POST ${base}/act`] = () => {
      beat = running;
      return json(202, { beat });
    };
    routes[`POST ${base}/cancel`] = () => json(200, {});
    routes[`POST ${base}/talk`] = () => json(201, { entry: entry(9, "talk", { seat_id: hostSeat.id, name: "Raf", text: "I listen" }, "") });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    const composer = await screen.findByTestId("composer");
    const box = within(composer).getByRole("textbox");
    fireEvent.change(box, { target: { value: "I open the door" } });
    fireEvent.keyDown(box, { key: "Enter" });

    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([{ text: "I open the door" }]));
    expect((box as HTMLTextAreaElement).value).toBe("");
    // Acting waits for the beat, and the words stay in the box; talk has a box of its own (DEL-199).
    fireEvent.change(box, { target: { value: "I listen" } });
    await waitFor(() => expect(actButton().disabled).toBe(true));
    expect(screen.getByTestId("thinking")).toBeTruthy();
    fireEvent.keyDown(box, { key: "Enter" });
    expect((box as HTMLTextAreaElement).value).toBe("I listen");
    expect(sent(fetchMock, "POST", `${base}/talk`)).toEqual([]);

    // Cancel is there while the beat runs.
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/cancel`)).toEqual([{}]));

    // Another campaign's beat changes nothing.
    FakeEventSource.emit("beat", { campaign_id: "cmp_0000000000ff", beat: { id: "beat_0000000000ff", status: "done" } });
    expect(actButton().disabled).toBe(true);

    beat = null;
    FakeEventSource.emit("beat", { campaign_id: CAMPAIGN, beat: { id: BEAT, status: "done", elapsed_s: 9 } });
    await waitFor(() => expect(actButton().disabled).toBe(false));
    expect(screen.queryByTestId("thinking")).toBeNull();
    expect(sent(fetchMock, "POST", `${base}/act`)).toHaveLength(1);
  });

  it("Ask shows the question and its answer in the story, folded, for this seat, with Share", async () => {
    const routes = playRoutes(playState(), [], { seats: [hostSeat, seat("seat_00000000000b", "Bo")] });
    const stored = [
      entry(6, "ask", { text: "What's a kobold?", original: "What's a kobold?", language: "en" }, ""),
      entry(7, "answer", { text: "A small, dog-like humanoid." }, ""),
    ].map((e) => ({ ...e, beat_id: null, audience: { seats: [hostSeat.id] } }));
    let story: unknown[] = [];
    let answer: (r: Response) => void = () => {};
    routes[`POST ${base}/ask`] = () => new Promise<Response>((resolve) => (answer = resolve)) as unknown as Response;
    routes[`GET ${base}/story?limit=50`] = () => json(200, { entries: story, has_more: false });
    routes[`POST ${base}/ask/${stored[1].id}/share`] = () =>
      json(201, {
        entry: entry(8, "talk", { seat_id: hostSeat.id, name: "Raf", text: "What's a kobold?", answer: "A small, dog-like humanoid.", shared: stored[1].id }, ""),
      });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    const box = within(await screen.findByTestId("composer")).getByRole("textbox");
    fireEvent.click(screen.getByTestId("mode-ask"));
    fireEvent.change(box, { target: { value: "What's a kobold?" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/ask`)).toEqual([{ question: "What's a kobold?" }]));
    const waiting = await within(screen.getByTestId("story")).findByTestId("asked");
    expect(waiting.textContent).toContain("What's a kobold?");
    expect(waiting.textContent).toContain("The DM is thinking…");

    // The server publishes both entries to the asker; the story isn't read again for them (DEL-168).
    const reads = fetchMock.mock.calls.filter(([p]) => p === `${base}/story?limit=50`).length;
    story = stored;
    answer(json(200, { answer: "A small, dog-like humanoid." }));
    for (const told of stored) FakeEventSource.emit("story", { campaign_id: CAMPAIGN, entry: told });
    const storyBox = screen.getByTestId("story");
    await waitFor(() => expect(storyBox.textContent).toContain("dog-like"));
    const [asked] = within(storyBox).getAllByTestId("asked");
    expect(within(storyBox).getAllByTestId("asked")).toHaveLength(1);
    expect(asked.tagName).toBe("DETAILS");
    expect(within(asked).getByTestId("only-you").textContent).toBe("Only you");
    // Folded or open, the summary says the answer is there to show or hide (DEL-261).
    expect(asked.querySelector(".asked-toggle")?.textContent).toBe("Show the answerHide the answer");
    expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([]);
    expect(fetchMock.mock.calls.filter(([p]) => p === `${base}/story?limit=50`).length).toBe(reads);

    fireEvent.click(within(asked).getByRole("button", { name: "Share with the table" }));
    await waitFor(() => expect(within(asked).getByText("Shared with the table")).toBeTruthy());
    expect(within(screen.getByTestId("talk-panel")).getByText("A small, dog-like humanoid.")).toBeTruthy();
    expect(screen.queryByTestId("ask-panel")).toBeNull();
  });

  it("Ask renders the answer's Markdown, escaped", async () => {
    const routes = playRoutes(playState(), [
      { ...entry(6, "ask", { text: "ooc: What are the stats of the item?" }, ""), beat_id: null, audience: { seats: [hostSeat.id] } },
      {
        ...entry(7, "answer", { text: "Durgan's gear:\n\n- **Chain mail:** AC 5\n- **Battle axe:** 1d8 <b>sharp</b>" }, ""),
        beat_id: null,
        audience: { seats: [hostSeat.id] },
      },
    ]);
    stubFetch(routes);
    renderWith(<Play />);

    const asked = await within(await screen.findByTestId("story")).findByTestId("asked");
    expect(within(asked).getByText("Chain mail:").tagName).toBe("STRONG");
    // The DM's text never becomes markup of its own.
    expect(asked.querySelector("b")).toBeNull();
    expect(asked.textContent).toContain("<b>sharp</b>");
  });

  it("a reload rebuilds from the story and picks up the stream", async () => {
    const routes = playRoutes(playState({ beat: { id: BEAT, status: "running", elapsed_s: 12 } }));
    routes[`GET ${base}/story?limit=50`] = () =>
      json(200, {
        entries: [
          entry(41, "player_act", { text: "We go down the stairs." }),
          entry(42, "dm_text", { text: "Damp stone steps lead down." }),
          entry(43, "tool", { name: "move_party" }),
        ],
        has_more: true,
      });
    routes[`GET ${base}/story?limit=50&before=41`] = () =>
      json(200, { entries: [entry(40, "recap", { text: "Last time: the road to the crypt." }, "beat_000000000000")], has_more: false });
    stubFetch(routes);
    renderWith(<Play />);

    const story = await screen.findByTestId("story");
    expect(await within(story).findByText("Damp stone steps lead down.")).toBeTruthy();
    expect(within(story).getByText("move_party")).toBeTruthy();
    // The beat still runs: Act waits, the indicator shows the time so far and the tools seen.
    await waitFor(() => expect(actButton().disabled).toBe(true));
    expect(screen.getByTestId("thinking").textContent).toContain("0:12");
    expect(screen.getByTestId("thinking").textContent).toContain("1 tool call");

    // The stream carries on where the page was.
    FakeEventSource.emit("story", {
      campaign_id: CAMPAIGN,
      entry: entry(44, "tool", { name: "roll_check" }),
    });
    expect(await within(story).findByText("roll_check")).toBeTruthy();
    expect(screen.getByTestId("thinking").textContent).toContain("2 tool calls");

    fireEvent.click(within(story).getByRole("button", { name: "Load earlier" }));
    expect(await within(story).findByText("Last time: the road to the crypt.")).toBeTruthy();
    expect(within(story).queryByRole("button", { name: "Load earlier" })).toBeNull();
    // Oldest first.
    expect(story.textContent!.indexOf("Last time")).toBeLessThan(story.textContent!.indexOf("Damp stone"));
  });
});

describe("the play screen at a table", () => {
  it("draws the party's portraits in the campaign's portrait style", async () => {
    const portrait = { kind: "traits", describe: "a young elf mage", seed: "chr_00000000000a" } as const;
    const ash = character("chr_00000000000a", "Ash");
    const routes = playRoutes(playState({ portrait_style: "pixel" }));
    routes[`GET ${base}/characters`] = () => json(200, [{ ...ash, sheet: { ...ash.sheet, portrait } }]);
    stubFetch(routes);
    renderWith(<Play />);
    const party = await screen.findByRole("region", { name: "Party" });
    const drawn = () => within(party).queryAllByRole("img", { name: "Ash" })[0]?.innerHTML ?? "";
    const asDrawn = (svg: string) => Object.assign(document.createElement("span"), { innerHTML: svg }).innerHTML;
    await waitFor(() => {
      const prefix = /id="([^"-]+)-/.exec(drawn())?.[1] ?? "";
      expect(prefix).not.toBe("");
      expect(drawn().replaceAll(prefix, "ID")).toBe(asDrawn(portraitSvg(portrait, 40, "ID", { style: "pixel" })));
    });
  });

  it("has three ways to speak: Act, Table talk and Ask the DM", async () => {
    const routes = playRoutes(playState(), [], { seats: [hostSeat, ana] });
    routes[`POST ${base}/act`] = () => json(202, { beat: { id: BEAT, status: "open", elapsed_s: 0, submitted: [hostSeat.id] } });
    routes[`POST ${base}/talk`] = () => json(201, { entry: entry(9, "talk", { seat_id: hostSeat.id, name: "Raf", text: "Back in five" }, "") });
    routes[`POST ${base}/ask`] = () => json(200, { answer: "Yes." });
    routes[`POST ${base}/typing`] = () => new Response(null, { status: 204 });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    const box = within(await screen.findByTestId("composer")).getByRole("textbox");
    const talkBox = within(screen.getByTestId("talk-box")).getByRole("textbox");
    fireEvent.change(talkBox, { target: { value: "Back in five" } });
    fireEvent.keyDown(talkBox, { key: "Enter" });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/talk`)).toEqual([{ text: "Back in five" }]));
    // Table talk goes to the talk, from its own box, not the story, and isn't an act.
    expect(await within(screen.getByTestId("talk-panel")).findByText("Back in five")).toBeTruthy();
    expect(screen.getByTestId("story").textContent).not.toContain("Back in five");
    expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([]);

    fireEvent.change(box, { target: { value: "Is it night?" } });
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/ask`)).toEqual([{ question: "Is it night?" }]));

    fireEvent.change(box, { target: { value: "I keep watch" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([{ text: "I keep watch" }]));
  });

  it("shows the seat's act in the open beat, which it can change, or Pass", async () => {
    const routes = playRoutes(playState(), [], { seats: [hostSeat, ana] });
    const open = { id: BEAT, status: "open", elapsed_s: 0, submitted: [hostSeat.id], deadline: null };
    let pending: unknown[] = [];
    const mine = (kind: string, text: string, secret = false) => ({
      seat_id: hostSeat.id, name: "Raf", kind, text, characters: [], private: secret, at: "2026-10-18T20:00:00Z",
    });
    routes[`GET ${base}/beat/pending`] = () => json(200, { pending });
    routes[`POST ${base}/act`] = (init) => {
      const body = JSON.parse(String(init?.body));
      pending = [mine("act", body.text, body.private === true)];
      return json(202, { beat: open });
    };
    routes[`POST ${base}/pass`] = () => {
      pending = [mine("pass", "")];
      return json(202, { beat: open });
    };
    routes[`POST ${base}/typing`] = () => new Response(null, { status: 204 });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    const box = within(await screen.findByTestId("composer")).getByRole("textbox") as HTMLTextAreaElement;
    const onlyDm = within(screen.getByTestId("only-dm")).getByRole("checkbox") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "I search the altar" } });
    fireEvent.click(onlyDm);
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([{ text: "I search the altar", private: true }]),
    );
    const myAct = await screen.findByTestId("my-act");
    expect(myAct.textContent).toContain("I search the altar");
    expect(within(myAct).getByTestId("private-act")).toBeTruthy();
    expect(onlyDm.checked).toBe(false);
    // An open beat waits for the table: the DM isn't answering yet.
    expect(screen.queryByTestId("thinking")).toBeNull();
    expect(screen.getByTestId("act").textContent).toBe("Replace my act");

    // Change puts the act's words and its flag back; nothing is sent until Act.
    fireEvent.click(within(myAct).getByRole("button", { name: "Change" }));
    expect(box.value).toBe("I search the altar");
    expect(onlyDm.checked).toBe(true);
    expect(sent(fetchMock, "POST", `${base}/act`)).toHaveLength(1);
    fireEvent.change(box, { target: { value: "I search the altar, quietly" } });
    fireEvent.click(screen.getByTestId("act"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([
        { text: "I search the altar", private: true },
        { text: "I search the altar, quietly", private: true },
      ]),
    );

    fireEvent.click(screen.getByTestId("pass"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/pass`)).toEqual([{}]));
    await waitFor(() => expect(screen.getByTestId("my-act").textContent).toContain("You pass"));
  });

  it("shows the others' acts so far, refreshed on a beat event", async () => {
    const open: RunningBeat = { id: BEAT, status: "open", elapsed_s: 0, submitted: [ana.id], deadline: null };
    const routes = playRoutes(playState({ beat: open }), [], { seats: [hostSeat, ana] });
    let pending = [{ seat_id: ana.id, name: "Ana", kind: "act", text: "I listen.", characters: [], private: false, at: "" }];
    routes[`GET ${base}/beat/pending`] = () => json(200, { pending });
    stubFetch(routes);
    renderWith(<Play />);

    expect((await screen.findByTestId("pending-act")).textContent).toContain("I listen.");
    pending = [{ ...pending[0], text: "I listen at the door." }];
    FakeEventSource.emit("beat", { campaign_id: CAMPAIGN, beat: open });
    await waitFor(() => expect(screen.getByTestId("pending-act").textContent).toContain("I listen at the door."));
  });

  it("offers the host the module's pregens while the party is empty, and acts with the names picked", async () => {
    const routes = playRoutes(playState({ party: [], positions: [] }), [], { seats: [hostSeat] });
    routes[`GET ${base}/pregens`] = () =>
      json(200, { pregens: [{ id: "ned", name: "Ned", race: "Human", class: "Thief", level: 3 }] });
    routes[`POST ${base}/act`] = () => json(202, { beat: { id: BEAT, status: "running", elapsed_s: 0 } });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    fireEvent.click(await screen.findByRole("checkbox", { name: /Ned/ }));
    fireEvent.click(screen.getByRole("button", { name: "Ask the DM to make them" }));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([
        { text: "Create the party from the module's pregenerated characters: Ned." },
      ]),
    );
  });

  it("acts for the characters picked, when the seat plays more than one", async () => {
    const routes = playRoutes(playState(), [], { seats: [hostSeat] });
    routes[`POST ${base}/act`] = () => json(202, { beat: { id: BEAT, status: "running", elapsed_s: 0 } });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    fireEvent.click(await screen.findByTestId("act-for"));
    fireEvent.click(screen.getByRole("menuitem", { name: "Several…" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Birch" }));
    const box = within(screen.getByTestId("composer")).getByRole("textbox");
    fireEvent.change(box, { target: { value: "We push on" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([
        { text: "We push on", characters: ["chr_00000000000a", "chr_00000000000c"] },
      ]),
    );
  });

  it("at a hotseat, takes each player's act in turn, then hands the screen on (DEL-365)", async () => {
    const hotseat = {
      on: true,
      seat_id: hostSeat.id,
      players: [
        { id: "hs_anna", name: "Anna", characters: ["chr_00000000000a"] },
        { id: "hs_ben", name: "Ben", characters: ["chr_00000000000b", "chr_00000000000c"] },
      ],
    };
    const open = { id: BEAT, status: "open", elapsed_s: 0, submitted: [hostSeat.id], deadline: null };
    const routes = playRoutes(playState({ hotseat }), [], { seats: [hostSeat] });
    let pending: unknown[] = [];
    routes[`GET ${base}/beat/pending`] = () => json(200, { pending });
    routes[`POST ${base}/act`] = (init) => {
      const body = JSON.parse(String(init?.body));
      pending = [{ seat_id: hostSeat.id, name: "Anna", kind: "act", text: body.text, characters: [], private: false, at: "", hotseat: body.player }];
      return json(202, { beat: open });
    };
    routes[`POST ${base}/pass`] = () => json(202, { beat: { ...open, status: "running" } });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    expect((await screen.findByTestId("hotseat-now")).textContent).toBe("Anna's turn");
    expect(screen.queryByTestId("only-dm"), "nothing is private on a shared screen").toBeNull();
    const box = within(screen.getByTestId("composer")).getByRole("textbox") as HTMLTextAreaElement;
    expect(box.placeholder).toBe("What does Anna do?");
    expect(screen.queryByTestId("act-for"), "Anna plays Ash alone").toBeNull();
    fireEvent.change(box, { target: { value: "I listen at the door" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([{ text: "I listen at the door", player: "hs_anna" }]),
    );
    await waitFor(() => expect(screen.getByTestId("hotseat-now").textContent).toBe("Pass the screen to Ben."));
    expect(box.placeholder).toBe("What does Ben do?");
    expect(screen.getByTestId("act-for").textContent, "Ben plays two").toContain("whole party");
    expect(screen.getByTestId("my-act").textContent).toContain("Anna");
    fireEvent.click(screen.getByTestId("pass"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/pass`)).toEqual([{ player: "hs_ben" }]));
  });

  it.each([
    ["the DM is still answering", "The DM is still answering."],
    ["The session hasn't started.", "The session hasn't started."],
  ])("says why an act is refused (409 %s)", async (refused, shown) => {
    const routes = playRoutes(playState(), [], { seats: [hostSeat] });
    routes[`POST ${base}/act`] = () => json(409, { error: refused });
    stubFetch(routes);
    renderWith(<Play />);

    const box = within(await screen.findByTestId("composer")).getByRole("textbox");
    fireEvent.change(box, { target: { value: "I open the door" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(await within(screen.getByTestId("composer")).findByText(shown)).toBeTruthy();
  });

  it("marks a seat submitted from a beat event, and shows the time left", async () => {
    stubFetch(playRoutes(playState(), [], { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    const indicators = await screen.findByTestId("seat-indicators");
    await waitFor(() => expect(indicators.querySelector(`[data-seat="${ana.id}"]`)?.getAttribute("data-state")).toBe("idle"));

    FakeEventSource.emit("typing", { campaign_id: CAMPAIGN, seat_id: ana.id, state: "typing" });
    expect(indicators.querySelector(`[data-seat="${ana.id}"]`)?.getAttribute("data-state")).toBe("typing");

    const deadline = new Date(Date.now() + 90_000).toISOString();
    FakeEventSource.emit("beat", {
      campaign_id: CAMPAIGN,
      beat_id: BEAT,
      status: "open",
      submitted: [ana.id],
      deadline,
      beat: { id: BEAT, status: "open", elapsed_s: 0, submitted: [ana.id], deadline },
    });
    await waitFor(() => expect(indicators.querySelector(`[data-seat="${ana.id}"]`)?.getAttribute("data-state")).toBe("submitted"));
    expect(screen.getByTestId("beat-timer").textContent).toMatch(/1:(29|30)/);
  });

  it("tells the others when the seat types, at most every 3 s, and idle after 5 s", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const routes = playRoutes(playState(), [], { seats: [hostSeat, ana] });
    routes[`POST ${base}/typing`] = () => new Response(null, { status: 204 });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    await screen.findByTestId("seat-indicators");
    const box = within(await screen.findByTestId("composer")).getByRole("textbox");

    fireEvent.change(box, { target: { value: "I" } });
    fireEvent.change(box, { target: { value: "I l" } });
    fireEvent.change(box, { target: { value: "I lo" } });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/typing`)).toEqual([{ state: "typing" }]));
    vi.advanceTimersByTime(3_100);
    fireEvent.change(box, { target: { value: "I loo" } });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/typing`)).toEqual([{ state: "typing" }, { state: "typing" }]));
    vi.advanceTimersByTime(5_100);
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/typing`)).toEqual([{ state: "typing" }, { state: "typing" }, { state: "idle" }]),
    );
  });

  it("alone at the table, sends no typing", async () => {
    const routes = playRoutes();
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    const box = within(await screen.findByTestId("composer")).getByRole("textbox");
    await waitFor(() => expect(fetchMock.mock.calls.some(([p]) => p === `${base}/seats`)).toBe(true));
    fireEvent.change(box, { target: { value: "I listen" } });
    expect(sent(fetchMock, "POST", `${base}/typing`)).toEqual([]);
    expect(screen.queryByTestId("seat-indicators")).toBeNull();
  });

  it("shows the Claude account's usage to the host alone", async () => {
    const usage = {
      at: "2026-10-24T07:40:00Z",
      status: "allowed",
      windows: [{ name: "five_hour", utilization: 0.82, resets_at: "2099-01-01T00:00:00Z" }],
    };
    const routes = playRoutes();
    routes[`GET ${base}/play/usage`] = () => json(200, { usage });
    stubFetch(routes);
    const shown = renderWith(<Play />);
    expect((await screen.findByTestId("account-usage")).textContent).toContain("5-hour 82%");
    shown.unmount();

    const seated = playRoutes(playState(), [], { me: me(ana), seats: [hostSeat, ana] });
    seated[`GET ${base}/maps/crypt/view?characters=chr_00000000000a`] = () => json(200, { svg: "<svg></svg>" });
    seated[`GET ${base}/story?limit=50&language=nl`] = () => json(200, { entries: [], has_more: false });
    const asked = stubFetch(seated);
    renderWith(<Play />);
    expect(await screen.findByTestId("composer")).toBeTruthy();
    expect(screen.queryByTestId("account-usage")).toBeNull();
    expect(asked.mock.calls.some(([p]) => String(p).endsWith("/play/usage"))).toBe(false);
  });

  it("gives host controls to the host and co-hosts only", async () => {
    const routes = playRoutes(playState(), [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`GET ${base}/maps/crypt/view?characters=chr_00000000000a`] = () => json(200, { svg: "<svg data-view='mine'></svg>" });
    const fetchMock = stubFetch(routes);
    const { unmount } = renderWith(<Play />);
    fireEvent.click(await screen.findByRole("tab", { name: "Table" }));
    expect(await screen.findByTestId("table-panel")).toBeTruthy();
    expect(screen.queryByTestId("host-controls")).toBeNull();
    // A player has none of the organiser's options, and no marching order arrows.
    expect(screen.queryByRole("button", { name: "Table options" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Move Ash down" })).toBeNull();
    // The map asks only for the seat's own characters, once its tab is opened.
    fireEvent.click(screen.getByRole("tab", { name: "Maps" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p]) => p === `${base}/maps/crypt/view?characters=chr_00000000000a`)).toBe(true),
    );
    expect(fetchMock.mock.calls.some(([p]) => String(p).includes("characters=chr_00000000000a,"))).toBe(false);
    unmount();

    const coHost = { ...ana, role: "cohost" as const };
    const again = playRoutes(playState(), [], { me: me(coHost), seats: [hostSeat, coHost] });
    again[`GET ${base}/invite`] = () => json(200, { url: "http://192.168.1.20:7810/join/tok", join_token: "tok" });
    stubFetch(again);
    renderWith(<Play />);
    fireEvent.click(await screen.findByRole("tab", { name: "Table" }));
    expect(await screen.findByTestId("host-controls")).toBeTruthy();
  });

  it("puts the look picker in the head, for every seat", async () => {
    stubFetch(playRoutes(playState(), [], { me: me(cy), seats: [hostSeat, cy] }));
    const { container } = renderWith(<Play />);
    expect(await screen.findByTestId("composer")).toBeTruthy();
    const look = within(container.querySelector("header.play-head") as HTMLElement).getByLabelText("Look");
    expect((look as HTMLSelectElement).value).toBe("delve");
  });

  it("links a seat to the campaign's ruleset in a new tab, from the head, an icon with a word (DEL-259)", async () => {
    stubFetch({ ...playRoutes(playState({ ruleset: "adnd2e" }), [], { me: me(cy), seats: [hostSeat, cy] }), "GET /api/me": () => json(200, me(cy)) });
    const { container } = renderWith(<Play />);
    const head = within(container.querySelector("header.play-head") as HTMLElement);
    const link = await head.findByRole("link", { name: "Rulesets (opens in a new tab)" });
    // With the campaign, which names the table's house rules (and, for an account, its table).
    await waitFor(() => expect(link.getAttribute("href")).toBe(`/rulesets/adnd2e?campaign=${CAMPAIGN}`));
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener");
    // The word shows where the header has room (CSS); the name says it opens a tab.
    expect(link.textContent?.trim()).toBe("Rules");
  });

  it("leaves the link out for the owner, whose side bar has Rulesets", async () => {
    const fetchMock = stubFetch({ ...playRoutes(playState({ ruleset: "adnd2e" }), [], { seats: [hostSeat] }), "GET /api/me": () => json(200, { ...me(), seat: null, account: null }) });
    const { container } = renderWith(<Play />);
    await screen.findByTestId("composer");
    await waitFor(() => expect(fetchMock.mock.calls.some(([p]) => p === "/api/me")).toBe(true));
    await act(async () => {});
    expect(within(container.querySelector("header.play-head") as HTMLElement).queryByRole("link", { name: "Rulesets (opens in a new tab)" })).toBeNull();
  });

  it("links to the Rulesets area while the campaign's ruleset isn't known", async () => {
    stubFetch({ ...playRoutes(playState(), [], { me: me(cy), seats: [hostSeat, cy] }), "GET /api/me": () => json(200, me(cy)) });
    const { container } = renderWith(<Play />);
    const head = within(container.querySelector("header.play-head") as HTMLElement);
    expect((await head.findByRole("link", { name: "Rulesets (opens in a new tab)" })).getAttribute("href")).toBe(`/rulesets?campaign=${CAMPAIGN}`);
  });

  it("counts the DM's tools for the host from beat_tools, and shows a player no count", async () => {
    const running = playState({ beat: { id: BEAT, status: "running", elapsed_s: 3 } });
    stubFetch(playRoutes(running, [], { seats: [hostSeat, ana] }));
    const { unmount } = renderWith(<Play />);
    await screen.findByTestId("thinking");
    FakeEventSource.emit("beat_tools", { campaign_id: CAMPAIGN, beat_id: BEAT, tool_count: 4 });
    await waitFor(() => expect(screen.getByTestId("thinking").textContent).toContain("4 tool calls"));
    unmount();

    const routes = playRoutes(running, [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`GET ${base}/maps/crypt/view?characters=chr_00000000000a`] = () => json(200, { svg: "<svg></svg>" });
    routes[`GET ${base}/story?limit=50&language=nl`] = () => json(200, { entries: [], has_more: false });
    stubFetch(routes);
    renderWith(<Play />);
    const thinking = await screen.findByTestId("thinking");
    await waitFor(() => expect(thinking.textContent).toContain("0:0"));
    expect(thinking.textContent).not.toContain("tool");
  });

  it("an observer talks and asks, but doesn't act", async () => {
    // The talk from its own box; the box under the story only asks.
    const routes = playRoutes(playState(), [], { me: me(cy), seats: [hostSeat, cy] });
    routes[`POST ${base}/talk`] = () => json(201, { entry: entry(9, "talk", { seat_id: cy.id, name: "Cy", text: "Go left!" }, "") });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    const composer = await screen.findByTestId("composer");
    await waitFor(() => expect(within(composer).queryByTestId("act")).toBeNull());
    const box = within(screen.getByTestId("talk-box")).getByRole("textbox");
    fireEvent.change(box, { target: { value: "Go left!" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/talk`)).toEqual([{ text: "Go left!" }]));
    expect(composer.dataset.channel).toBe("ask");
    expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([]);
  });

  it("a late joiner scrolls back to the start of the story, a page at a time (G1)", async () => {
    // The sentinel above the first entry is in sight whenever it is observed: the pages are short. It is seen twice
    // at once, as a browser may: one load runs at a time.
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(private callback: (entries: { isIntersecting: boolean }[]) => void) {}
        observe() {
          queueMicrotask(() => {
            this.callback([{ isIntersecting: true }]);
            this.callback([{ isIntersecting: true }]);
          });
        }
        disconnect() {}
      },
    );
    const routes = playRoutes(playState(), [], { me: me(cy), seats: [hostSeat, cy] });
    routes[`GET ${base}/story?limit=50`] = () =>
      json(200, { entries: [entry(120, "dm_text", { text: "The newest words." })], has_more: true });
    routes[`GET ${base}/story?limit=50&before=120`] = () =>
      json(200, { entries: [entry(60, "dm_text", { text: "The middle of it." })], has_more: true });
    routes[`GET ${base}/story?limit=50&before=60`] = () =>
      json(200, { entries: [entry(3, "dm_text", { text: "The first words this seat may see." })], has_more: false });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    const story = await screen.findByTestId("story");
    expect(await within(story).findByText("The start of the story")).toBeTruthy();
    expect(story.textContent).toContain("The first words this seat may see.");
    expect(story.textContent!.indexOf("The first words")).toBeLessThan(story.textContent!.indexOf("The middle"));
    expect(story.textContent!.indexOf("The middle")).toBeLessThan(story.textContent!.indexOf("The newest"));
    // Each page once, and nothing past the start.
    const pages = fetchMock.mock.calls.map(([url]) => String(url)).filter((url) => url.includes("/story?"));
    const talk = pages.filter((url) => url.includes("kind=talk"));
    expect(pages.filter((url) => !talk.includes(url))).toEqual([
      `${base}/story?limit=50`,
      `${base}/story?limit=50&before=120`,
      `${base}/story?limit=50&before=60`,
    ]);
    // The talk's own page (DEL-219), read once: the story's scrolling never pages the talk.
    expect(talk).toEqual([`${base}/story?limit=50&kind=talk`]);
  });

  it("the talk panel has its own lines, past a story page of narration (DEL-219)", async () => {
    const routes = playRoutes(playState(), [], { me: me(cy), seats: [hostSeat, cy] });
    routes[`GET ${base}/story?limit=50`] = () =>
      json(200, { entries: [entry(120, "dm_text", { text: "The newest words." })], has_more: true });
    routes[`GET ${base}/story?limit=50&kind=talk`] = () =>
      json(200, {
        entries: [{ ...entry(7, "talk", { seat_id: hostSeat.id, name: "Raf", text: "Mind the stairs." }), beat_id: null }],
        has_more: false,
      });
    stubFetch(routes);
    renderWith(<Play />);
    const panel = await screen.findByTestId("talk-panel");
    expect(await within(panel).findByText("Mind the stairs.")).toBeTruthy();
    expect(within(panel).queryByText("Nobody has said anything at the table yet.")).toBeNull();
  });

  it("says so in the talk box when the talk's lines can't be read", async () => {
    const routes = playRoutes(playState(), [], { me: me(cy), seats: [hostSeat, cy] });
    routes[`GET ${base}/story?limit=50&kind=talk`] = () => json(500, { error: "The talk is out of reach." });
    stubFetch(routes);
    renderWith(<Play />);
    const talkBox = await screen.findByTestId("talk-box");
    expect((await within(talkBox).findByRole("alert")).textContent).toContain("The talk is out of reach.");
  });

  it("reads the story in the seat's language, and takes translations as they come", async () => {
    const dutch = { ...ana };
    const routes = playRoutes(playState(), [], { me: me(dutch), seats: [hostSeat, dutch] });
    routes[`GET ${base}/maps/crypt/view?characters=chr_00000000000a`] = () => json(200, { svg: "<svg></svg>" });
    routes[`GET ${base}/story?limit=50&language=nl`] = () =>
      json(200, {
        entries: [
          { ...entry(1, "dm_text", { text: "The door opens." }), translation: { language: "nl", text: "De deur gaat open.", status: "done" } },
          entry(2, "dm_text", { text: "A cold wind blows." }),
        ],
        has_more: false,
      });
    stubFetch(routes);
    renderWith(<Play />);
    const story = await screen.findByTestId("story");
    expect(await within(story).findByText("De deur gaat open.")).toBeTruthy();

    FakeEventSource.emit("translation", {
      campaign_id: CAMPAIGN,
      entry_id: entry(2, "dm_text", {}).id,
      language: "nl",
      text: "Een koude",
      status: "translating",
    });
    expect(within(story).getByText("Een koude").closest(".entry")!.querySelector("[data-testid=translating]")).toBeTruthy();
    FakeEventSource.emit("translation", {
      campaign_id: CAMPAIGN,
      entry_id: entry(2, "dm_text", {}).id,
      language: "nl",
      text: "Een koude wind waait.",
      status: "done",
    });
    expect(within(story).getByText("Een koude wind waait.")).toBeTruthy();
    expect(story.textContent).not.toContain("A cold wind blows.");
  });

  it("on a phone, shows the story and the composer, with Map, Party and Table one tap away", async () => {
    stubScreen(true);
    stubFetch(playRoutes(playState(), [], { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    const tabs = await screen.findByTestId("phone-tabs");
    expect(screen.getByTestId("story")).toBeTruthy();
    expect(screen.getByTestId("composer")).toBeTruthy();
    // No side-by-side panels.
    expect(screen.queryByTestId("table-panel")).toBeNull();
    expect(screen.queryByRole("region", { name: "Party" })).toBeNull();

    fireEvent.click(within(tabs).getByRole("button", { name: "Table" }));
    const table = screen.getByTestId("phone-screen");
    expect(within(table).getByTestId("table-panel")).toBeTruthy();
    fireEvent.click(within(tabs).getByRole("button", { name: "Party" }));
    expect(within(screen.getByTestId("phone-screen")).getByRole("region", { name: "Party" })).toBeTruthy();
    fireEvent.click(within(screen.getByTestId("phone-screen")).getByRole("button", { name: "Back to the story" }));
    expect(screen.queryByTestId("phone-screen")).toBeNull();
  });

  it("above 600 px, shows the panels and no bottom bar", async () => {
    stubScreen(false);
    stubFetch(playRoutes(playState(), [], { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    expect(await screen.findByTestId("play-aside")).toBeTruthy();
    expect(screen.queryByTestId("phone-tabs")).toBeNull();
  });

  it("beside the story: Party, Maps and Table tabs, the party first; Table holds the table panel, then the host's controls", async () => {
    stubScreen(false);
    const routes = playRoutes(playState(), [], { seats: [hostSeat, ana] });
    routes[`GET ${base}/invite`] = () => json(200, { url: "http://192.168.1.20:7810/join/tok", join_token: "tok" });
    stubFetch(routes);
    renderWith(<Play />);
    const aside = await screen.findByTestId("play-aside");
    const tabs = within(aside).getByRole("tablist", { name: "Sidebar" });
    expect(within(tabs).getAllByRole("tab").map((b) => b.textContent)).toEqual(["Party", "Maps", "Table"]);
    expect(within(tabs).getByRole("tab", { name: "Party" }).getAttribute("aria-selected")).toBe("true");
    expect(within(aside).getByRole("region", { name: "Party" })).toBeTruthy();
    // A tab mounts when it is first opened (DEL-168): the table panel isn't there yet.
    expect(within(aside).queryByTestId("table-panel")).toBeNull();

    fireEvent.click(within(tabs).getByRole("tab", { name: "Table" }));
    await screen.findByTestId("host-controls");
    const table = aside.querySelector('[data-panel="table"]') as HTMLElement;
    expect(table.hidden).toBe(false);
    const order = [...table.children].map((child) => child.getAttribute("data-panel"));
    expect(order).toEqual(["table-panel", "host"]);
    expect(within(table).getByTestId("table-panel").contains(screen.getByTestId("host-controls"))).toBe(false);
    expect(within(aside).queryByRole("region", { name: "Party" })).toBeNull();

    fireEvent.click(within(tabs).getByRole("tab", { name: "Maps" }));
    expect(within(aside).getByRole("tablist", { name: "Panels" })).toBeTruthy();
    // Once opened, a tab stays, out of sight.
    expect(within(aside).getByTestId("table-panel").closest("[hidden]")).toBeTruthy();
  });

  it("puts a dot on a tab out of sight whose panel changed, until it is opened", async () => {
    stubScreen(false);
    let state = playState();
    const routes = playRoutes(state, [], { seats: [hostSeat, ana] });
    routes[`GET ${base}/play/state`] = () => json(200, state);
    stubFetch(routes);
    renderWith(<Play />);
    const tabs = within(await screen.findByTestId("play-aside")).getByRole("tablist", { name: "Sidebar" });
    await screen.findByTestId("talk-panel");
    const dot = (name: string) => screen.queryByTestId(`dot-${name}`);
    expect([dot("party"), dot("map"), dot("table")]).toEqual([null, null, null]);

    // Ana talks while the party is on screen: the talk is in sight under the tabs (DEL-199), so no tab gets a dot.
    FakeEventSource.emit("story", { campaign_id: CAMPAIGN, entry: entry(5, "talk", { seat_id: ana.id, name: "Ana", text: "Left!" }, "") });
    expect(await within(screen.getByTestId("talk-panel")).findByText("Left!")).toBeTruthy();
    expect(dot("table")).toBeNull();
    fireEvent.click(within(tabs).getByRole("tab", { name: /Table/ }));

    // Birch is hurt and the party moves while Table is on screen: Party and Maps get dots.
    state = playState({
      party: state.party.map((m) => (m.name === "Birch" ? { ...m, hp: 1 } : m)),
      positions: [{ map: "crypt", location: "room.hall", label: "Hall", characters: ["Ash", "Birch", "Cedar"] }],
    });
    FakeEventSource.emit("characters", { campaign_id: CAMPAIGN });
    await waitFor(() => expect(dot("party")).toBeTruthy());
    expect(dot("map")).toBeTruthy();
    fireEvent.click(within(tabs).getByRole("tab", { name: /Party/ }));
    await waitFor(() => expect(dot("party")).toBeNull());
    expect(dot("map")).toBeTruthy();
  });

  it("on a phone, puts the same dots on Map, Party and Table", async () => {
    stubScreen(true);
    stubFetch(playRoutes(playState(), [], { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    const tabs = await screen.findByTestId("phone-tabs");
    // The seats are in once the Table screen names Ana.
    fireEvent.click(within(tabs).getByTestId("tab-table"));
    expect((await within(screen.getByTestId("phone-screen")).findAllByText("Ana")).length).toBeGreaterThan(0);
    fireEvent.click(within(screen.getByTestId("phone-screen")).getByRole("button", { name: "Back to the story" }));
    FakeEventSource.emit("story", { campaign_id: CAMPAIGN, entry: entry(5, "talk", { seat_id: ana.id, name: "Ana", text: "Left!" }, "") });
    await waitFor(() => expect(within(tabs).queryByTestId("dot-table")).toBeTruthy());
    fireEvent.click(within(tabs).getByTestId("tab-table"));
    await waitFor(() => expect(within(tabs).queryByTestId("dot-table")).toBeNull());
  });

  it("reads its story afresh when the enemies' dice change sides of the screen (DEL-270)", async () => {
    const goblin = { who: "Goblin", side: null, what: "attack", detail: null, dice: "d20", faces: [17], total: 17 };
    let story = [entry(1, "dm_text", { text: "A goblin leaps." }), entry(2, "tool", { name: "resolve_attack", dice: [goblin] })];
    const routes = playRoutes(playState(), [], { seats: [hostSeat, ana] });
    routes[`GET ${base}/story?limit=50`] = () => json(200, { entries: story, has_more: false });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    expect(await screen.findByText("Goblin, attack — d20: 17")).toBeTruthy();
    const reads = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("/story?limit=50")).length;
    const before = reads();

    // Paid images alone leave the story as it is.
    FakeEventSource.emit("play_options", { campaign_id: CAMPAIGN });
    await waitFor(() => expect(reads()).toBe(before));
    // Back behind the screen: the page the server answers has the row no more, and it goes from this one too.
    story = [story[0]];
    FakeEventSource.emit("play_options", { campaign_id: CAMPAIGN, story: true });
    await waitFor(() => expect(screen.queryByText("Goblin, attack — d20: 17")).toBeNull());
    expect(screen.getByText("A goblin leaps.")).toBeTruthy();
  });

  it("gives every acting seat Paint this scene beside Act and Ask the DM while a scene can be painted", async () => {
    let state = playState({ scene_painting: false });
    const routes = playRoutes(state, [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`GET ${base}/play/state`] = () => json(200, state);
    routes[`POST ${base}/scene`] = () => json(202, { image_id: "img_00000000000a", status: "painting" });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    const composer = await screen.findByTestId("composer");
    expect(within(composer).queryByRole("button", { name: "Paint this scene…" })).toBeNull();

    // The host turns paid images on: the seats read the state again.
    state = playState({ scene_painting: true, scene_paid: true });
    FakeEventSource.emit("play_options", { campaign_id: CAMPAIGN });
    const paint = await within(composer).findByRole("button", { name: "Paint this scene…" });
    // It asks first, and says it costs the host money (DEL-258); Cancel paints nothing.
    fireEvent.click(paint);
    let dialog = await screen.findByRole("alertdialog", { name: "Paint this scene?" });
    expect(dialog.textContent).toContain("costs the host money");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(sent(fetchMock, "POST", `${base}/scene`)).toEqual([]);
    fireEvent.click(paint);
    dialog = await screen.findByRole("alertdialog", { name: "Paint this scene?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Paint it" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/scene`)).toEqual([{}]));
    expect(await within(composer).findByText("The scene is being painted.")).toBeTruthy();
    // One at a time: it waits while that one paints.
    expect((within(composer).getByRole("button", { name: "Paint this scene…" }) as HTMLButtonElement).disabled).toBe(true);

    // Its picture lands in the story: the line goes (DEL-174).
    FakeEventSource.emit("story", {
      campaign_id: CAMPAIGN,
      entry: entry(5, "scene", { image_id: "img_00000000000a", caption: "The bridge" }, ""),
    });
    await waitFor(() => expect(within(composer).queryByText("The scene is being painted.")).toBeNull());
  });

  it("lets an old failure go once something newer is tried (DEL-174)", async () => {
    const routes = playRoutes(playState({ scene_painting: true }), [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`POST ${base}/scene`] = () => json(409, { error: "The painter is busy." });
    routes[`POST ${base}/act`] = () => json(202, { beat: { id: "beat_000000000002", status: "running" } });
    stubFetch(routes);
    renderWith(<Play />);
    const composer = await screen.findByTestId("composer");
    fireEvent.click(await within(composer).findByRole("button", { name: "Paint this scene…" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Paint this scene?" });
    // A free painter: no cost note.
    expect(dialog.textContent).toContain("It comes in a minute or so.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Paint it" }));
    expect((await within(composer).findByRole("alert")).textContent).toContain("The painter is busy.");

    const box = within(composer).getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "I light a torch" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(within(composer).queryByRole("alert")).toBeNull());
  });

  it("shows a scene still painting as a placeholder in the story, read again on a scenes event", async () => {
    let state = playState({ scene_painting: true });
    const routes = playRoutes(state, [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`GET ${base}/play/state`] = () => json(200, state);
    stubFetch(routes);
    renderWith(<Play />);
    await screen.findByTestId("composer");
    expect(screen.queryByTestId("painting-scene")).toBeNull();

    state = playState({ scene_painting: true, painting_scenes: [{ image_id: "img_00000000000a", caption: "The bridge" }] });
    FakeEventSource.emit("scenes", { campaign_id: CAMPAIGN });
    expect(await screen.findByTestId("painting-scene")).toBeTruthy();

    state = playState({ scene_painting: true, painting_scenes: [] });
    FakeEventSource.emit("scenes", { campaign_id: CAMPAIGN });
    await waitFor(() => expect(screen.queryByTestId("painting-scene")).toBeNull());
  });

  it("gives an observer no Paint this scene", async () => {
    stubFetch(playRoutes(playState({ scene_painting: true }), [], { me: me(cy), seats: [hostSeat, cy] }));
    renderWith(<Play />);
    const composer = await screen.findByTestId("composer");
    expect(within(composer).queryByRole("button", { name: "Paint this scene" })).toBeNull();
  });

  it("puts no dot on Table for this seat's own talk", async () => {
    stubScreen(false);
    stubFetch(playRoutes(playState(), [], { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    await screen.findByTestId("talk-panel");
    FakeEventSource.emit("story", { campaign_id: CAMPAIGN, entry: entry(5, "talk", { seat_id: hostSeat.id, name: "Raf", text: "Back in five" }, "") });
    FakeEventSource.emit("story", { campaign_id: CAMPAIGN, entry: entry(6, "dm_text", { text: "A cold wind." }) });
    expect(await within(screen.getByTestId("story")).findByText("A cold wind.")).toBeTruthy();
    expect(screen.queryByTestId("dot-table")).toBeNull();
  });

  it("shows the tool rows to the host, and a player only what the characters perceive (Review Focus 4)", async () => {
    const story = [entry(1, "dm_text", { text: "You hear a click." }), entry(2, "tool", { name: "saving_throw" })];
    const english = { ...ana, language: "en" };
    const routes = playRoutes(playState(), story, { me: me(english), seats: [hostSeat, english] });
    routes[`GET ${base}/maps/crypt/view?characters=chr_00000000000a`] = () => json(200, { svg: "<svg></svg>" });
    stubFetch(routes);
    const { unmount } = renderWith(<Play />);
    expect(await within(await screen.findByTestId("story")).findByText("You hear a click.")).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId("story").textContent).not.toContain("saving_throw"));
    unmount();

    stubFetch(playRoutes(playState(), story, { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    expect(await within(await screen.findByTestId("story")).findByText("saving_throw")).toBeTruthy();
  });

  it("offers a player with no character a way to choose one: the join page's picker", async () => {
    const lost = { ...ana, characters: [] };
    const routes = playRoutes(playState(), [], { me: me(lost), seats: [hostSeat, lost] });
    routes[`POST ${base}/characters/chr_00000000000a/claim`] = () => json(200, {});
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    fireEvent.click(await screen.findByRole("button", { name: "Choose or ask for a character" }));
    const picker = await screen.findByRole("dialog", { name: "Pick your characters" });
    fireEvent.click(await within(picker).findByTestId("join-character-chr_00000000000a"));
    fireEvent.click(within(picker).getByTestId("join-play"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/characters/chr_00000000000a/claim`)).toEqual([{}]));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Pick your characters" })).toBeNull());
  });

  it("before the session starts, a request for a character waits in the box, not refused and lost (DEL-254)", async () => {
    const lost = { ...ana, characters: [] };
    const gathering = playState({ table: { ...playState().table, state: "gathering", solo: false } });
    const routes = playRoutes(gathering, [], { me: me(lost), seats: [hostSeat, lost] });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    fireEvent.click(await screen.findByRole("button", { name: "Choose or ask for a character" }));
    const picker = await screen.findByRole("dialog", { name: "Pick your characters" });
    const box = await within(picker).findByTestId("join-make-one");
    await within(picker).findByText(/The host hasn't started the session yet/);
    fireEvent.change(box, { target: { value: "A halfling thief, please" } });
    fireEvent.click(within(picker).getByTestId("join-play"));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Pick your characters" })).toBeNull());
    expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([]);
    expect(localStorage.getItem(`delve.heldRequest.${CAMPAIGN}`)).toBe("A halfling thief, please");
  });

  it("puts a held request in the box under the story, once (DEL-254)", async () => {
    localStorage.setItem(`delve.heldRequest.${CAMPAIGN}`, "A halfling thief, please");
    stubFetch(playRoutes(playState(), [], { seats: [hostSeat] }));
    const { unmount } = renderWith(<Play />);
    const box = within(await screen.findByTestId("composer")).getByRole("textbox") as HTMLTextAreaElement;
    await waitFor(() => expect(box.value).toBe("A halfling thief, please"));
    expect(localStorage.getItem(`delve.heldRequest.${CAMPAIGN}`)).toBe("");
    unmount();
  });

  it("offers no such choice to a seat that plays a character, the host or an observer", async () => {
    for (const [mine, label] of [[ana, "player"], [hostSeat, "host"], [cy, "observer"]] as const) {
      const routes = playRoutes(playState(), [], { me: me(mine), seats: [hostSeat, mine] });
      routes[`GET ${base}/maps/crypt/view?characters=chr_00000000000a`] = () => json(200, { svg: "<svg></svg>" });
      routes[`GET ${base}/invite`] = () => json(200, { url: "http://192.168.1.20:7810/join/tok", join_token: "tok" });
      stubFetch(routes);
      const { unmount } = renderWith(<Play />);
      await screen.findByTestId("composer");
      await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([p]) => p === `${base}/seats`)).toBe(true));
      expect(screen.queryByRole("button", { name: "Choose or ask for a character" }), label).toBeNull();
      unmount();
    }
  });
});

describe("the play screen's world (plan 6)", () => {
  it("shows the date and the weather in the head", async () => {
    stubScreen(false);
    stubFetch(playRoutes(playState({ date: "4 Planting 576 CY", weather: { label: "light rain", effect: "" } })));
    renderWith(<Play />);
    expect(await screen.findByText("Session 1 · morning · 4 Planting 576 CY · light rain")).toBeTruthy();
  });

  it("says when the session is over (DEL-182)", async () => {
    stubScreen(false);
    stubFetch(playRoutes(playState({ session_over: true })));
    renderWith(<Play />);
    expect(await screen.findByText(/^Session 1 is over · /)).toBeTruthy();
  });

  it("on desktop, the World panel is a tab beside the map", async () => {
    stubScreen(false);
    stubFetch({ ...playRoutes(), ...worldRoutes() });
    renderWith(<Play />);
    const aside = await screen.findByTestId("play-aside");
    fireEvent.click(within(aside).getByRole("tab", { name: "Maps" }));
    const side = aside.querySelector('[data-panel="map"]') as HTMLElement;
    const tabs = within(side).getByRole("tablist");
    expect(within(tabs).getByRole("tab", { name: "Map" }).getAttribute("aria-selected")).toBe("true");
    expect(within(side).queryByText("Find the relic")).toBeNull();
    fireEvent.click(within(tabs).getByRole("tab", { name: "World" }));
    expect(await within(side).findByText("Find the relic")).toBeTruthy();
    expect(within(side).queryByRole("region", { name: "Map" })).toBeNull();
  });

  it("on a phone, World is the fourth screen of the bottom bar", async () => {
    stubScreen(true);
    stubFetch({ ...playRoutes(), ...worldRoutes() });
    renderWith(<Play />);
    const tabs = await screen.findByTestId("phone-tabs");
    expect(within(tabs).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Map",
      "Party",
      "Table",
      "World",
      "Setting",
    ]);
    fireEvent.click(within(tabs).getByRole("button", { name: "World" }));
    const world = screen.getByTestId("phone-screen");
    expect(world.getAttribute("aria-label")).toBe("World");
    expect(await within(world).findByText("Find the relic")).toBeTruthy();
  });

  it("on desktop, the side tabs are Map, World and Setting; Setting shows the campaign's setting", async () => {
    stubScreen(false);
    stubFetch({
      ...playRoutes(),
      [`GET ${base}/setting`]: () => json(200, { id: "greyhawk", title: "Greyhawk", kinds: [], calendar: null }),
    });
    renderWith(<Play />);
    const aside = await screen.findByTestId("play-aside");
    fireEvent.click(within(aside).getByRole("tab", { name: "Maps" }));
    const side = aside.querySelector('[data-panel="map"]') as HTMLElement;
    const tabs = within(side).getByRole("tablist", { name: "Panels" });
    expect(within(tabs).getAllByRole("tab").map((b) => b.textContent)).toEqual(["Map", "World", "Setting"]);
    fireEvent.click(within(tabs).getByRole("tab", { name: "Setting" }));
    expect(await within(side).findByTestId("setting-panel")).toBeTruthy();
    expect(within(side).queryByRole("region", { name: "Map" })).toBeNull();
  });

  it("on a phone, Setting is the fifth screen of the bottom bar", async () => {
    stubScreen(true);
    stubFetch({ ...playRoutes(), [`GET ${base}/setting`]: () => json(404, { error: "This campaign has no setting." }) });
    renderWith(<Play />);
    const tabs = await screen.findByTestId("phone-tabs");
    fireEvent.click(within(tabs).getByRole("button", { name: "Setting" }));
    const shown = screen.getByTestId("phone-screen");
    expect(shown.getAttribute("aria-label")).toBe("Setting");
    expect(await within(shown).findByText("This campaign has no setting.")).toBeTruthy();
  });

  it("on a world event reads the state again, and leaves the world to the app's handler (P15)", async () => {
    stubScreen(true);
    const fetchMock = stubFetch({ ...playRoutes(), ...worldRoutes() });
    renderWith(<Play />);
    fireEvent.click(within(await screen.findByTestId("phone-tabs")).getByRole("button", { name: "World" }));
    await screen.findByText("Find the relic");
    const reads = (path: string) => fetchMock.mock.calls.filter(([p]) => p === `${base}/${path}`).length;
    const [world, state] = [reads("world"), reads("play/state")];
    FakeEventSource.emit("world", { campaign_id: CAMPAIGN });
    await waitFor(() => expect(reads("play/state")).toBe(state + 1));
    // App.tsx reads the world on the same event: a second read here was the same request twice.
    expect(reads("world")).toBe(world);
  });

  it("shows a setting's fact while the DM thinks", async () => {
    stubScreen(false);
    const routes = playRoutes(playState({ beat: { id: BEAT, status: "running", elapsed_s: 2 } }));
    routes[`GET ${base}/lore/random?n=20`] = () => json(200, { facts: [{ text: "Hardby has a Despotrix.", category: "" }] });
    stubFetch(routes);
    renderWith(<Play />);
    const thinking = await screen.findByTestId("thinking");
    expect(await within(thinking.parentElement as HTMLElement).findByText("Hardby has a Despotrix.")).toBeTruthy();
  });
});

describe("the session and raised hands (DEL-199)", () => {
  const table = (over: Partial<TableSession> = {}): TableSession => ({
    state: "playing",
    since: null,
    solo: false,
    absent: {},
    hands: [],
    away: [],
    ...over,
  });

  it("while the table gathers, the talk is wide, Act waits and the host starts the session", async () => {
    stubScreen(false);
    let state = playState({ table: table({ state: "gathering" }) });
    const routes = playRoutes(state, [], { seats: [hostSeat, { ...ana, present: false }] });
    routes[`GET ${base}/play/state`] = () => json(200, state);
    routes[`POST ${base}/session/start`] = () => {
      state = playState({ table: table(), beat: { id: BEAT, status: "running", elapsed_s: 0 } as RunningBeat });
      return json(202, { table: table(), beat: { id: BEAT, status: "running", elapsed_s: 0 } });
    };
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);

    const notice = await screen.findByTestId("session-notice");
    expect(notice.textContent).toContain("Waiting for the table");
    expect(screen.getByTestId("play-aside").className).toContain("talk-wide");
    expect((screen.getByTestId("act") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("composer-hint").textContent).toContain("once the host starts the session");

    fireEvent.click(screen.getByTestId("session-start"));
    const dialog = await screen.findByTestId("start-dialog");
    expect(dialog.textContent).toContain("Ana isn't here");
    fireEvent.click(within(dialog).getByLabelText(/sits this session out/));
    fireEvent.click(within(dialog).getByTestId("start-confirm"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/session/start`)).toEqual([{ absent: { chr_00000000000a: "out" } }]),
    );
    await waitFor(() => expect(screen.queryByTestId("session-notice")).toBeNull());
    expect(screen.getByTestId("play-aside").className).not.toContain("talk-wide");
  });

  it("Narrow and Widen switch the talk's width by hand", async () => {
    stubScreen(false);
    stubFetch(playRoutes(playState({ table: table({ state: "break" }) }), [], { seats: [hostSeat, seat("seat_00000000000b", "Bo")] }));
    renderWith(<Play />);
    await waitFor(() => expect(screen.getByTestId("play-aside").className).toContain("talk-wide"));
    fireEvent.click(screen.getByTestId("talk-widen"));
    await waitFor(() => expect(screen.getByTestId("play-aside").className).not.toContain("talk-wide"));
  });

  it("the host takes a break and comes back; a player sees no session buttons", async () => {
    stubScreen(false);
    let state = playState({ table: table() });
    const routes = playRoutes(state);
    routes[`GET ${base}/play/state`] = () => json(200, state);
    routes[`POST ${base}/session/break`] = () => {
      state = playState({ table: table({ state: "break" }) });
      return json(200, { table: table({ state: "break" }) });
    };
    routes[`POST ${base}/session/resume`] = () => {
      state = playState({ table: table() });
      return json(200, { table: table() });
    };
    const fetchMock = stubFetch(routes);
    const { unmount } = renderWith(<Play />);
    fireEvent.click(await screen.findByTestId("session-break"));
    expect((await screen.findByTestId("session-notice")).textContent).toContain("On a break");
    fireEvent.click(await screen.findByTestId("session-resume"));
    await waitFor(() => expect(screen.queryByTestId("session-notice")).toBeNull());
    expect(sent(fetchMock, "POST", `${base}/session/break`)).toEqual([{}]);
    expect(sent(fetchMock, "POST", `${base}/session/resume`)).toEqual([{}]);
    unmount();

    stubFetch(playRoutes(playState({ table: table() }), [], { me: me(ana), seats: [hostSeat, ana] }));
    renderWith(<Play />);
    await screen.findByTestId("composer");
    expect(screen.queryByTestId("session-controls")).toBeNull();
  });

  it("steps away with a part for the characters, says so by the Act box, and comes back (DEL-224)", async () => {
    stubScreen(false);
    let state = playState({ table: table() });
    const routes = playRoutes(state, [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`GET ${base}/play/state`] = () => json(200, state);
    routes[`POST ${base}/away`] = () => json(200, { table: table() });
    routes[`DELETE ${base}/away/${ana.id}`] = () => json(200, { table: table() });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    await screen.findByTestId("composer");
    expect(screen.queryByTestId("away-line")).toBeNull();

    fireEvent.click(await screen.findByTestId("step-away"));
    const form = screen.getByTestId("step-away-form");
    fireEvent.click(within(form).getByRole("button", { name: "Are played cautiously by the DM" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/away`)).toEqual([{ part: "in_character" }]));

    state = playState({ table: table({ away: [{ seat_id: ana.id, at: "2026-10-27T20:31:00+00:00", part: "in_character" }] }) });
    FakeEventSource.emit("table", { campaign_id: CAMPAIGN });
    const line = await screen.findByTestId("away-line");
    expect(line.textContent).toContain("the table plays on without waiting for you");
    expect(screen.queryByTestId("step-away"), "once away, I'm back is by the Act box").toBeNull();
    const mine = screen.getByTestId("seat-indicators").querySelector(`[data-seat="${ana.id}"]`);
    expect(mine?.textContent).toContain("Stepped away");
    fireEvent.click(within(line).getByTestId("im-back"));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([url, init]) => String(url) === `${base}/away/${ana.id}` && init?.method === "DELETE"),
      ).toHaveLength(1),
    );
  });

  it("says why Step away failed, by the Act box", async () => {
    stubScreen(false);
    const routes = playRoutes(playState({ table: table() }), [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`POST ${base}/away`] = () => json(409, { error: "The session has ended." });
    stubFetch(routes);
    renderWith(<Play />);
    fireEvent.click(await screen.findByTestId("step-away"));
    fireEvent.click(within(screen.getByTestId("step-away-form")).getByRole("button", { name: "Are played cautiously by the DM" }));
    const composer = screen.getByTestId("composer");
    expect((await within(composer).findByRole("alert")).textContent).toContain("The session has ended.");
  });

  it("offers no Step away while the table gathers", async () => {
    stubScreen(false);
    stubFetch(playRoutes(playState({ table: table({ state: "gathering" }) }), [], { me: me(ana), seats: [hostSeat, ana] }));
    renderWith(<Play />);
    await screen.findByTestId("raise-hand");
    expect(screen.queryByTestId("step-away")).toBeNull();
  });

  it("shows raised hands above the tabs and by the Act box, read again on a table event", async () => {
    stubScreen(false);
    let state = playState({ table: table() });
    const routes = playRoutes(state, [], { me: me(ana), seats: [hostSeat, ana] });
    routes[`GET ${base}/play/state`] = () => json(200, state);
    routes[`POST ${base}/hand`] = () => json(200, { table: table() });
    const fetchMock = stubFetch(routes);
    renderWith(<Play />);
    await screen.findByTestId("composer");
    expect(screen.queryByTestId("raised-hands")).toBeNull();

    state = playState({ table: table({ hands: [{ seat_id: hostSeat.id, at: "2026-10-27T20:31:00+00:00", point: "Her shadow is missing." }] }) });
    FakeEventSource.emit("table", { campaign_id: CAMPAIGN });
    const strip = await screen.findByTestId("raised-hands");
    expect(strip.textContent).toContain(hostSeat.name);
    expect(strip.textContent).toContain("Her shadow is missing.");
    expect(within(strip).queryByRole("button", { name: "Lower" }), "a player lowers only their own").toBeNull();
    expect(screen.getByTestId("hands-line").textContent).toContain("wants a word before anyone acts");

    fireEvent.click(screen.getByTestId("raise-hand"));
    fireEvent.click(screen.getByTestId("raise-hand-confirm"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/hand`)).toEqual([{ point: null }]));
  });
});

