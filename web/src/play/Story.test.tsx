import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { EventsContext } from "../api";
import Story, { GalleryStrip, actor, limitEnd } from "./Story";
import type { DiceLine, SeatRole, StoryEntry } from "./api";
import { CAMPAIGN, entry, hostSeat, json, sent, stubFetch } from "./testing";

function renderStory(entries: StoryEntry[], role?: SeatRole, language = "en") {
  return render(
    <I18nProvider language={language}>
      <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role={role} />
    </I18nProvider>,
  );
}

describe("Story", () => {
  it("a screen reader hears each new entry once it is whole, not the loaded pages or each streamed word", () => {
    const story = (entries: StoryEntry[], running: boolean) => (
      <I18nProvider language="en">
        <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role="player" running={running} />
      </I18nProvider>
    );
    const loaded = entry(1, "dm_text", { text: "Long ago." });
    const { rerender } = render(story([loaded], false));
    expect(screen.getByTestId("story").getAttribute("aria-live")).toBeNull();
    const announce = screen.getByTestId("story-announce");
    expect(announce.getAttribute("aria-live")).toBe("polite");
    expect(announce.textContent).toBe("");

    const reply = (text: string) => ({ ...entry(2, "dm_text", { text }), live: true });
    rerender(story([loaded, reply("The door")], true));
    rerender(story([loaded, reply("The door **creaks** open.")], true));
    expect(announce.textContent, "still being written").toBe("");
    rerender(story([loaded, reply("The door **creaks** open.")], false));
    expect(announce.textContent).toBe("The door creaks open.");

    const said = { ...entry(3, "say", { text: "Who goes there?", speaker: { id: "npc_1", name: "Guard", portrait: null } }), live: true };
    rerender(story([loaded, reply("The door **creaks** open."), said], false));
    expect(announce.textContent).toBe("Guard: Who goes there?");
  });

  it("an empty story shows the book's ink drawing above its first line, never a picture, and a begun story neither", () => {
    const { unmount } = renderStory([], "player");
    const story = screen.getByTestId("story");
    expect(within(story).queryByRole("img")).toBeNull();
    const art = story.querySelector(".story-empty-art");
    expect(art).not.toBeNull();
    const line = within(story).getByText("Say what your character does in the box below, and the DM takes it from there.");
    expect(art!.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    unmount();
    renderStory([entry(1, "dm_text", { text: "The door creaks." })], "player");
    expect(screen.getByTestId("story").querySelector(".story-empty-art")).toBeNull();
  });

  it("before the host starts, the empty story says the story waits for them, not to act (DEL-262)", () => {
    render(
      <I18nProvider language="en">
        <Story entries={[]} hasMore={false} onLoadEarlier={() => {}} role="player" waiting />
      </I18nProvider>,
    );
    expect(screen.getByTestId("story-empty").textContent).toContain("The story starts when the host starts the session.");
    expect(screen.queryByText(/Say what your character does/)).toBeNull();
  });

  it("shows tool rows to the host, a co-host without refusals, and no other seat (Review Focus 4)", () => {
    const entries = [
      entry(1, "dm_text", { text: "The door creaks." }),
      entry(2, "tool", { name: "saving_throw" }),
      entry(3, "tool", { name: "combat_round", failed: true }),
    ];
    const rows = () => [...screen.getByTestId("story").querySelectorAll(".tool-row")].map((r) => r.textContent);
    const { unmount } = renderStory(entries, "host");
    expect(rows()).toEqual(["saving_throw", "combat_roundrefused"]);
    unmount();
    for (const [role, shown] of [["cohost", ["saving_throw"]], ["player", []], ["observer", []], [undefined, []]] as const) {
      const { unmount: done } = renderStory(entries, role);
      expect(rows(), String(role)).toEqual(shown);
      expect(screen.getByTestId("story").textContent).toContain("The door creaks.");
      done();
    }
  });

  it("shows a tool row's dice under it, a batch's step by step, and a player only the rows with dice (DEL-270)", () => {
    const line = (who: string | null, what: string | null, dice: string, faces: number[], extra: Partial<DiceLine> = {}) => ({
      who, side: null, what, detail: null, dice, faces, total: faces.reduce((a, b) => a + b, 0), ...extra,
    });
    const entries = [
      entry(1, "dm_text", { text: "Steel rings." }),
      entry(2, "tool", { name: "roll", dice: [line(null, null, "3d20", [14, 7, 18], { detail: "Reggi wrestling, three falls" })] }),
      entry(3, "dm_text", { text: "Reggi wins." }),
      entry(4, "tool", {
        name: "batch",
        steps: [
          { step: 0, name: "resolve_attack", dice: [line("Garrek", "attack", "d20", [19]), line("Garrek", "damage", "d8", [6])] },
          { step: 2, name: "surprise_check", dice: [line(null, "surprise", "d10", [3], { side: "party" })] },
        ],
      }),
      entry(5, "dm_text", { text: "Then quiet." }),
      entry(6, "tool", { name: "get_character" }),
    ];
    const lines = () => [...screen.getByTestId("story").querySelectorAll(".tool-dice li")].map((li) => li.textContent?.trim());
    const expected = [
      "Reggi wrestling, three falls — 3d20: 14, 7, 18 (39)",
      "Garrek, attack — d20: 19",
      "Garrek, damage — d8: 6",
      "the party, surprise — d10: 3",
    ];
    for (const role of ["player", "observer", "cohost"] as const) {
      const { unmount } = renderStory(entries, role);
      expect(lines(), role).toEqual(expected);
      expect(screen.getAllByRole("list", { name: "Dice" }).length, role).toBe(3);
      const names = [...screen.getByTestId("story").querySelectorAll(".tool-row")].map((r) => r.textContent);
      // A player or observer sees no row without dice for it; a co-host every row, as before.
      expect(names, role).toEqual(role === "cohost" ? ["roll", "resolve_attack", "surprise_check", "get_character"] : ["roll", "resolve_attack", "surprise_check"]);
      unmount();
    }
    renderStory([entry(1, "tool", { name: "roll", failed: true, dice: [line("Garrek", "attack", "d20", [2])] })], "player");
    expect(lines()).toEqual([]);
  });

  it("words the dice in the reader's language, the DM's own words as they are", () => {
    renderStory(
      [entry(1, "tool", { name: "saving_throw", dice: [{ who: null, side: "enemy", what: "save", detail: "spell", dice: "d20", faces: [12], total: 12 }] })],
      "player",
      "nl",
    );
    expect(screen.getByTestId("story").querySelector(".tool-dice li")?.textContent?.trim()).toBe("een vijand, reddingsworp (spell) — d20: 12");
    expect(screen.getByRole("list", { name: "Dobbelstenen" })).toBeTruthy();
  });

  it("lands at the newest entry, and follows new ones unless the reader scrolled up", () => {
    const first = [entry(1, "dm_text", { text: "One." }), entry(2, "dm_text", { text: "Two." })];
    const { rerender } = renderStory(first, "host");
    const story = screen.getByTestId("story");
    Object.defineProperty(story, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(story, "clientHeight", { configurable: true, value: 200 });
    const show = (entries: StoryEntry[]) =>
      rerender(
        <I18nProvider language="en">
          <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role="host" />
        </I18nProvider>,
      );
    show([...first, entry(3, "dm_text", { text: "Three." })]);
    expect(story.scrollTop).toBe(1000);

    // The reader scrolls up to read back: a new entry leaves them there.
    story.scrollTop = 300;
    fireEvent.scroll(story);
    show([...first, entry(3, "dm_text", { text: "Three." }), entry(4, "dm_text", { text: "Four." })]);
    expect(story.scrollTop).toBe(300);

    // Back at the bottom, it follows again.
    story.scrollTop = 800;
    fireEvent.scroll(story);
    Object.defineProperty(story, "scrollHeight", { configurable: true, value: 1400 });
    show([...first, entry(3, "dm_text", { text: "Three." }), entry(4, "dm_text", { text: "Four." }), entry(5, "dm_text", { text: "Five." })]);
    expect(story.scrollTop).toBe(1400);
  });

  it("folds the host's consecutive tool rows into one chip that opens to their names (G3, P-b)", () => {
    renderStory(
      [
        entry(1, "dm_text", { text: "The door creaks." }),
        entry(2, "tool", { name: "batch" }),
        entry(3, "tool", { name: "create_character", failed: true }),
        entry(4, "tool", { name: "module_lookup" }),
        entry(5, "dm_text", { text: "A rat squeaks." }),
        entry(6, "tool", { name: "roll_check" }),
      ],
      "host",
    );
    const story = screen.getByTestId("story");
    const chips = story.querySelectorAll("details.tool-chip");
    expect(chips).toHaveLength(1);
    expect(chips[0].querySelector("summary")?.textContent).toBe("3 tools");
    expect((chips[0] as HTMLDetailsElement).open).toBe(false);
    expect([...chips[0].querySelectorAll(".tool-row")].map((r) => r.textContent)).toEqual([
      "batch",
      "create_characterrefused",
      "module_lookup",
    ]);
    // A lone tool row stays a row; the narration is untouched.
    expect(within(story).getByText("roll_check").closest("details")).toBeNull();
    expect(story.textContent).toContain("A rat squeaks.");
  });

  it("counts and shows a batch as its steps, never as 'batch'", () => {
    const steps = (names: string[], failed = -1) =>
      names.map((name, step) => ({ step, name, ...(step === failed ? { failed: true } : {}) }));
    const entries = [
      entry(1, "dm_text", { text: "The goblins charge." }),
      entry(2, "tool", { name: "batch", steps: steps(["roll", "roll", "advance_time", "move_party", "roll_check"]) }),
      entry(3, "tool", { name: "batch", steps: steps(["attack", "attack", "damage", "damage", "morale_check"], 4) }),
      entry(4, "dm_text", { text: "One flees." }),
      entry(5, "tool", { name: "batch", steps: steps(["advance_time", "encounter_check"]) }),
    ];
    renderStory(entries, "host");
    const chips = screen.getByTestId("story").querySelectorAll("details.tool-chip");
    expect([...chips].map((c) => c.querySelector("summary")?.textContent)).toEqual(["10 tools", "2 tools"]);
    const rows = [...chips[0].querySelectorAll(".tool-row")].map((r) => r.textContent);
    expect(rows).toHaveLength(10);
    expect(rows).not.toContain("batch");
    expect(rows.at(-1)).toBe("morale_checkrefused");
    // DEL-117: each row has its kind's icon; the chip shows each kind once, in the order they came.
    const kinds = (el: Element) => [...el.querySelectorAll("svg.tool-kind")].map((i) => i.getAttribute("data-kind"));
    expect(kinds(chips[0].querySelector("summary")!)).toEqual(["chance", "time", "place", "other"]);
    expect(kinds(chips[0].querySelectorAll(".tool-row")[0])).toEqual(["chance"]);
    expect(chips[0].querySelector("svg.tool-kind")!.classList).toContain("tone-chance");
  });

  it("names the tools in the reader's language, English keeping the tool's own name", () => {
    const rows = [entry(1, "tool", { name: "add_item" }), entry(2, "tool", { name: "batch", steps: [{ step: 0, name: "roll" }] })];
    renderStory(rows, "host", "nl");
    const chip = screen.getByTestId("story").querySelector("details.tool-chip")!;
    const labels = [...chip.querySelectorAll(".tool-row")].map((r) => r.textContent);
    expect(labels).toEqual(["Voorwerp toevoegen", "Dobbelen"]);
    expect(chip.querySelector(".tool-label")!.getAttribute("title")).toBe("add_item");
  });

  it("keeps the tool names in English", () => {
    renderStory([entry(1, "tool", { name: "add_item" }), entry(2, "tool", { name: "roll" })], "host");
    const rows = [...screen.getByTestId("story").querySelectorAll(".tool-row .tool-name")].map((r) => r.textContent);
    expect(rows).toEqual(["add_item", "roll"]);
  });

  it("leaves a batch's refused steps out for a co-host", () => {
    const steps = [{ step: 0, name: "roll" }, { step: 1, name: "move_party", failed: true }, { step: 2, name: "roll_check" }];
    renderStory([entry(1, "tool", { name: "batch", steps })], "cohost");
    const chip = screen.getByTestId("story").querySelector("details.tool-chip")!;
    expect(chip.querySelector("summary")?.textContent).toBe("2 tools");
  });

  it("loads the earlier page by itself when the reader scrolls to the top (G1)", () => {
    const observed: Element[] = [];
    let fire: (entries: { isIntersecting: boolean }[]) => void = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: (entries: { isIntersecting: boolean }[]) => void) {
          fire = callback;
        }
        observe(el: Element) {
          observed.push(el);
        }
        disconnect() {}
      },
    );
    try {
      const onLoadEarlier = vi.fn();
      render(
        <I18nProvider language="en">
          <Story entries={[entry(51, "dm_text", { text: "Late." })]} hasMore onLoadEarlier={onLoadEarlier} />
        </I18nProvider>,
      );
      expect(observed.map((el) => el.getAttribute("data-testid"))).toEqual(["story-top"]);
      fire([{ isIntersecting: false }]);
      expect(onLoadEarlier).not.toHaveBeenCalled();
      fire([{ isIntersecting: true }]);
      expect(onLoadEarlier).toHaveBeenCalledOnce();
      // The button stays, for keyboards.
      expect(screen.getByRole("button", { name: "Load earlier" })).toBeTruthy();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("says where the story starts once there is nothing earlier", () => {
    const { unmount } = renderStory([entry(1, "dm_text", { text: "The first words." })]);
    const story = screen.getByTestId("story");
    expect(story.firstElementChild?.textContent).toBe("The start of the story");
    expect(within(story).queryByRole("button", { name: "Load earlier" })).toBeNull();
    unmount();
    render(
      <I18nProvider language="en">
        <Story entries={[entry(51, "dm_text", { text: "Late." })]} hasMore onLoadEarlier={() => {}} />
      </I18nProvider>,
    );
    expect(screen.getByTestId("story").textContent).not.toContain("The start of the story");
  });

  it("keeps the reader's place when an earlier page comes in", () => {
    const late = [entry(51, "dm_text", { text: "Late." }), entry(52, "dm_text", { text: "Later." })];
    const show = (entries: StoryEntry[]) => (
      <I18nProvider language="en">
        <Story entries={entries} hasMore onLoadEarlier={() => {}} />
      </I18nProvider>
    );
    const { rerender } = render(show(late));
    const story = screen.getByTestId("story");
    Object.defineProperty(story, "clientHeight", { configurable: true, value: 200 });
    Object.defineProperty(story, "scrollHeight", { configurable: true, value: 1000 });
    story.scrollTop = 0;
    fireEvent.scroll(story);
    // The earlier page adds 600 px above: the reader stays on the entry they were reading.
    Object.defineProperty(story, "scrollHeight", { configurable: true, value: 1600 });
    rerender(show([entry(50, "dm_text", { text: "Early." }), ...late]));
    expect(story.scrollTop).toBe(600);
  });

  it("offers a way back to the latest once the newest entry is out of sight, and counts what came in since (DEL-95)", () => {
    const show = (entries: StoryEntry[]) => (
      <I18nProvider language="en">
        <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role="host" />
      </I18nProvider>
    );
    const two = [entry(1, "dm_text", { text: "One." }), entry(2, "dm_text", { text: "Two." })];
    const { rerender } = render(show(two));
    const story = screen.getByTestId("story");
    Object.defineProperty(story, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(story, "clientHeight", { configurable: true, value: 200 });
    // The story box ends 200 px down the window; the newest entry's top is where `newestTop` says.
    let newestTop = 150;
    const rect = vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      return (this === story ? { top: 0, bottom: 200 } : { top: newestTop, bottom: newestTop + 40 }) as DOMRect;
    });
    try {
      story.scrollTop = 750; // a little up, the newest entry still in sight
      fireEvent.scroll(story);
      expect(screen.queryByRole("button", { name: /Back to the latest/ })).toBeNull();
      newestTop = 260; // less than a screen up, but the newest is below the box
      story.scrollTop = 700;
      fireEvent.scroll(story);
      expect(screen.getByRole("button", { name: "Back to the latest" })).toBeTruthy();

      rerender(show([...two, entry(3, "dm_text", { text: "Three." })]));
      expect(screen.getByRole("button", { name: "Back to the latest · 1 new" })).toBeTruthy();
      rerender(show([...two, entry(3, "dm_text", { text: "Three." }), entry(4, "dm_text", { text: "Four." })]));
      fireEvent.click(screen.getByRole("button", { name: "Back to the latest · 2 new" }));
      expect(story.scrollTop).toBe(1000);
      expect(screen.queryByRole("button", { name: /Back to the latest/ })).toBeNull();
    } finally {
      rect.mockRestore();
    }
  });

  it("renders entries and escapes HTML", () => {
    const onLoadEarlier = vi.fn();
    const { container } = render(
      <I18nProvider language="en">
        <Story
          entries={[
            entry(1, "player_act", { text: "I open the <b>door</b>" }),
            entry(2, "dm_text", {
              text: 'The door creaks. <img src=x onerror="alert(1)"> It is **heavy**.\n\n> "Who goes there?"',
            }),
            entry(3, "tool", { name: "roll_check" }),
            entry(4, "tool", { name: "move_party", failed: true }),
            entry(5, "dm_error", { message: "The DM didn't answer: timeout" }),
            entry(6, "ask", { text: "What's a kobold?" }),
          ]}
          hasMore
          onLoadEarlier={onLoadEarlier}
          role="host"
        />
      </I18nProvider>,
    );
    const story = screen.getByTestId("story");

    // Nothing the DM writes becomes markup: the tags are text, Markdown still renders.
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(story.textContent).toContain('<img src=x onerror="alert(1)">');
    expect(story.textContent).toContain("I open the <b>door</b>");
    expect(within(story).getByText("heavy").tagName).toBe("STRONG");
    // Read-aloud and speech blockquotes are styled apart.
    expect(container.querySelector("blockquote.read-aloud")?.textContent).toBe('"Who goes there?"');

    // Tool rows are the tool's name only (spec §7.5): no inputs, no result; a refusal says so, without its message.
    expect(within(story).getByText("roll_check").closest(".tool-row")?.textContent).toBe("roll_check");
    expect(within(story).getByText("refused").closest(".tool-row.failed")).toBeTruthy();
    expect(within(story).getByText("The DM didn't answer: timeout").closest(".dm-error")).toBeTruthy();
    // A question to the DM shows folded, marked "Only you", waiting for its answer (plan 7 Task 18).
    const asked = within(story).getByTestId("asked");
    expect(asked.tagName).toBe("DETAILS");
    expect(asked.textContent).toContain("What's a kobold?");
    expect(asked.textContent).toContain("The DM is thinking…");

    fireEvent.click(within(story).getByRole("button", { name: "Load earlier" }));
    expect(onLoadEarlier).toHaveBeenCalledOnce();
  });

  it("renders an image entry as an <img> with its caption", () => {
    const { container } = render(
      <I18nProvider language="en">
        <Story
          entries={[
            entry(1, "tool", { name: "show_image" }),
            entry(2, "image", { asset: "gate", caption: "The gate of <b>Saint Vellis</b>" }),
            entry(3, "image", { asset: "plan/v2", caption: "" }),
          ]}
          hasMore={false}
          onLoadEarlier={() => {}}
        />
      </I18nProvider>,
    );
    const figures = container.querySelectorAll("figure.entry.image");
    expect(figures).toHaveLength(2);

    // Served by the campaign's image route, which answers only for its player images.
    const gate = figures[0].querySelector("img");
    expect(gate?.getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/images/gate`);
    expect(gate?.getAttribute("alt")).toBe("The gate of <b>Saint Vellis</b>");
    // The caption is text, never markup.
    expect(figures[0].querySelector("figcaption")?.textContent).toBe("The gate of <b>Saint Vellis</b>");
    expect(container.querySelector("b")).toBeNull();

    // Without a caption: no figcaption, and a generic alt text.
    const plan = figures[1].querySelector("img");
    expect(plan?.getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/images/plan%2Fv2`);
    expect(plan?.getAttribute("alt")).toBe("An image from the DM");
    expect(figures[1].querySelector("figcaption")).toBeNull();
  });

  it("marks an entry addressed to some characters as only yours, and keeps table talk out", () => {
    render(
      <I18nProvider language="en">
        <Story
          entries={[
            entry(1, "dm_text", { text: "Everyone hears the bell." }),
            { ...entry(2, "dm_text", { text: "Only Garrek sees the ghost." }), audience: { characters: ["chr_00000000000a"] } },
            { ...entry(3, "talk", { seat_id: "seat_00000000000a", name: "Ana", text: "brb" }, ""), beat_id: null },
          ]}
          hasMore={false}
          onLoadEarlier={() => {}}
        />
      </I18nProvider>,
    );
    const story = screen.getByTestId("story");
    const ghost = within(story).getByText("Only Garrek sees the ghost.").closest(".entry")!;
    expect(ghost.classList.contains("addressed")).toBe(true);
    expect(within(ghost as HTMLElement).getByTestId("only-you").textContent).toBe("Only you");
    const bell = within(story).getByText("Everyone hears the bell.").closest(".entry")!;
    expect(bell.querySelector("[data-testid=only-you]")).toBeNull();
    expect(story.textContent).not.toContain("brb");
  });

  it("shows an entry in the seat's language when translated, else the English marked as translating", () => {
    render(
      <I18nProvider language="en">
        <Story
          entries={[
            { ...entry(1, "dm_text", { text: "The door opens." }), translation: { language: "nl", text: "De deur gaat open.", status: "done" } },
            { ...entry(2, "dm_text", { text: "A cold wind blows." }), translation: { language: "nl", text: "", status: "translating" } },
            { ...entry(3, "dm_text", { text: "Rats scatter." }), translation: { language: "nl", text: "", status: "failed" } },
            {
              ...entry(4, "player_act", { seat_id: "seat_00000000000a", name: "Ana", text: "I look.", original: "Ik kijk.", characters: ["chr_00000000000a"] }),
              translation: { language: "nl", text: "Ik kijk.", status: "done" },
            },
            entry(5, "player_act", { seat_id: hostSeat.id, name: "Raf", text: "I wait." }),
          ]}
          hasMore={false}
          onLoadEarlier={() => {}}
          mySeatId={hostSeat.id}
          names={{ chr_00000000000a: "Garrek" }}
        />
      </I18nProvider>,
    );
    const story = screen.getByTestId("story");
    expect(within(story).getByText("De deur gaat open.")).toBeTruthy();
    expect(story.textContent).not.toContain("The door opens.");
    const wind = within(story).getByText("A cold wind blows.").closest(".entry")!;
    expect(wind.querySelector("[data-testid=translating]")?.textContent).toBe("translating…");
    const rats = within(story).getByText("Rats scatter.").closest(".entry")!;
    expect(rats.querySelector("[data-testid=not-translated]")).toBeTruthy();
    // Another seat's act carries its name and its characters; my own says "You".
    expect(within(story).getByText("Ik kijk.").closest(".entry")!.textContent).toContain("Ana · Garrek");
    expect(within(story).getByText("I wait.").closest(".entry")!.textContent).toContain("You");
  });

  it("gathers the images the DM has shown in a gallery strip", () => {
    const { container } = render(
      <I18nProvider language="en">
        <GalleryStrip
          entries={[
            entry(1, "dm_text", { text: "Look." }),
            entry(2, "image", { asset: "gate", caption: "The gate" }),
            entry(3, "image", { asset: "plan", caption: "" }),
          ]}
        />
      </I18nProvider>,
    );
    const strip = screen.getByTestId("gallery");
    const images = strip.querySelectorAll("img");
    expect([...images].map((i) => i.getAttribute("src"))).toEqual([
      `/api/campaigns/${CAMPAIGN}/images/plan`,
      `/api/campaigns/${CAMPAIGN}/images/gate`,
    ]);
    expect(container.querySelector("a")).toBeNull();

    // A thumbnail opens the picture enlarged, as in the story, not in a new tab (DEL-309).
    fireEvent.click(within(strip).getByRole("button", { name: "Enlarge: The gate" }));
    const shown = screen.getByRole("dialog", { name: "The gate" });
    expect(within(shown).getByRole("img").getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/images/gate`);
    fireEvent.keyDown(shown, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("enlarges an image the DM shows, and a painted scene, on a click; a click or Escape closes it", () => {
    renderStory([
      entry(1, "image", { asset: "gate", caption: "The gate" }),
      { ...entry(2, "scene", { image_id: "img_00000000000a", caption: "" }), beat_id: null },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Enlarge: The gate" }));
    const shown = screen.getByRole("dialog", { name: "The gate" });
    expect(within(shown).getByRole("img", { name: "The gate" }).getAttribute("src")).toBe(
      `/api/campaigns/${CAMPAIGN}/images/gate`,
    );
    fireEvent.click(within(shown).getByRole("img"));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Enlarge: A painted scene" }));
    const scene = screen.getByRole("dialog", { name: "A painted scene" });
    expect(within(scene).getByRole("img").getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/pictures/img_00000000000a`);
    fireEvent.keyDown(scene, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows a placeholder for each scene still painting, at the end, till its picture comes in", () => {
    const painting = [
      { image_id: "img_00000000000a", caption: "The bridge" },
      { image_id: "img_00000000000b", caption: "" },
    ];
    const story = (entries: StoryEntry[]) => (
      <I18nProvider language="en">
        <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} paintingScenes={painting} />
      </I18nProvider>
    );
    const { container, rerender } = render(story([]));
    expect(container.querySelector(".placeholder")).toBeNull();
    const skeletons = screen.getAllByTestId("painting-scene");
    expect(skeletons.map((s) => s.querySelector("figcaption")?.textContent)).toEqual([
      "The bridge · Painting the scene…",
      "Painting the scene…",
    ]);
    expect(skeletons[0].querySelector("img")).toBeNull();
    expect(within(skeletons[0]).getByRole("img", { name: "Painting the scene…" })).toBeTruthy();

    // The bridge landed before the state was read again: its picture stands in its place.
    rerender(story([{ ...entry(1, "scene", { image_id: "img_00000000000a", caption: "The bridge" }), beat_id: null }]));
    expect(screen.getAllByTestId("painting-scene")).toHaveLength(1);
    expect(container.querySelectorAll("figure.entry.scene:not(.painting)")).toHaveLength(1);
  });

  it("says a painting scene's place in the painter's queue while it waits its turn", () => {
    const painting = [
      { image_id: "img_00000000000a", caption: "The bridge", provider: "assetgen", queue: 3 },
      { image_id: "img_00000000000b", caption: "", provider: "assetgen", queue: null },
    ];
    render(
      <I18nProvider language="en">
        <Story entries={[]} hasMore={false} onLoadEarlier={() => {}} paintingScenes={painting} />
      </I18nProvider>,
    );
    expect(screen.getAllByTestId("painting-scene").map((s) => s.querySelector("figcaption")?.textContent)).toEqual([
      "The bridge · Waiting in assetgen's queue: number 3.",
      "Painting the scene…",
    ]);
  });

  it("shows a painted scene with its caption, and puts it in the gallery strip", () => {
    const entries = [
      entry(1, "dm_text", { text: "Look." }),
      entry(2, "image", { asset: "gate", caption: "The gate" }),
      { ...entry(3, "scene", { image_id: "img_00000000000a", caption: "The <i>bridge</i> at dusk" }), beat_id: null },
      { ...entry(4, "scene", { image_id: "img_00000000000b", caption: "" }), beat_id: null },
    ];
    const { container } = renderStory(entries);
    const scenes = container.querySelectorAll("figure.entry.scene");
    expect(scenes).toHaveLength(2);
    const bridge = scenes[0].querySelector("img");
    expect(bridge?.getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/pictures/img_00000000000a`);
    expect(bridge?.getAttribute("alt")).toBe("The <i>bridge</i> at dusk");
    expect(scenes[0].querySelector("figcaption")?.textContent).toBe("The <i>bridge</i> at dusk");
    expect(container.querySelector("i")).toBeNull();
    expect(scenes[1].querySelector("img")?.getAttribute("alt")).toBe("A painted scene");
    expect(scenes[1].querySelector("figcaption")).toBeNull();

    render(
      <I18nProvider language="en">
        <GalleryStrip entries={entries} />
      </I18nProvider>,
    );
    const strip = screen.getByTestId("gallery");
    expect([...strip.querySelectorAll("img")].map((i) => i.getAttribute("src"))).toEqual([
      `/api/campaigns/${CAMPAIGN}/pictures/img_00000000000b`,
      `/api/campaigns/${CAMPAIGN}/pictures/img_00000000000a`,
      `/api/campaigns/${CAMPAIGN}/images/gate`,
    ]);
  });

  it("shows no gallery before the DM has shown an image", () => {
    render(
      <I18nProvider language="en">
        <GalleryStrip entries={[entry(1, "dm_text", { text: "Look." })]} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId("gallery")).toBeNull();
  });
  it("shows a said line with its speaker, and animates only the newest live one (Review Focus 4)", () => {
    const tira = { id: "npc_00000000000a", name: "Tira", portrait: null };
    const line = (seq: number, text: string, live = false): StoryEntry => ({
      ...entry(seq, "say", { speaker: tira, mood: "smile", text } as never),
      live,
    });
    // 300 entries from history, 40 of them said lines: nothing plays.
    const history = Array.from({ length: 300 }, (_, i) =>
      i % 7 === 0 && i < 280 ? line(i + 1, `Line ${i + 1}.`) : entry(i + 1, "dm_text", { text: `Narration ${i + 1}.` }),
    );
    expect(history.filter((e) => e.kind === "say")).toHaveLength(40);
    const { rerender } = renderStory(history, "player");
    const lines = () => [...screen.getByTestId("story").querySelectorAll(".said")];
    expect(lines()).toHaveLength(40);
    expect(lines()[0].textContent).toContain("Tira");
    expect(lines().filter((l) => l.getAttribute("data-live") === "true")).toEqual([]);

    // Two lines arrive live: only the newer one animates.
    const show = (entries: StoryEntry[]) =>
      rerender(
        <I18nProvider language="en">
          <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role="player" />
        </I18nProvider>,
      );
    show([...history, line(301, "First, this.", true), entry(302, "dm_text", { text: "She pauses." }), line(303, "Then that.", true)]);
    const live = lines().filter((l) => l.getAttribute("data-live") === "true");
    expect(live).toHaveLength(1);
    expect(live[0]).toBe(lines().at(-1));
  });

  describe("the story's right-click menu", () => {
    function rightClick(el: Element) {
      fireEvent.mouseDown(el, { button: 2 });
      fireEvent.contextMenu(el, { button: 2 });
    }

    it("copies an entry's text", async () => {
      const writeText = vi.fn(async () => {});
      vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
      renderStory([entry(1, "dm_text", { text: "The door **creaks**." })], "player");
      rightClick(screen.getByText("creaks"));
      fireEvent.click(await screen.findByRole("menuitem", { name: "Copy the text" }));
      expect(writeText).toHaveBeenCalledWith("The door **creaks**.");
      expect(screen.queryByRole("menuitem", { name: "Share with the table" })).toBeNull();
      vi.unstubAllGlobals();
    });

    it("shares an answer not yet shared", async () => {
      const onShare = vi.fn();
      render(
        <I18nProvider language="en">
          <Story
            entries={[entry(1, "ask", { text: "What's a kobold?" }), entry(2, "answer", { text: "A small reptilian humanoid." })]}
            hasMore={false}
            onLoadEarlier={() => {}}
            onShare={onShare}
          />
        </I18nProvider>,
      );
      rightClick(screen.getByText("A small reptilian humanoid."));
      const items = await screen.findAllByRole("menuitem");
      fireEvent.click(items.find((i) => i.textContent === "Share with the table")!);
      expect(onShare).toHaveBeenCalledWith("ste_000000000002");
    });

    it("leaves the browser's menu over selected text, and outside the entries", () => {
      renderStory([entry(1, "dm_text", { text: "The door creaks." })], "player");
      const selection = vi.spyOn(window, "getSelection").mockReturnValue({ toString: () => "door" } as Selection);
      rightClick(screen.getByText("The door creaks."));
      expect(screen.queryByRole("menu")).toBeNull();
      selection.mockRestore();
      rightClick(screen.getByText("The start of the story"));
      expect(screen.queryByRole("menu")).toBeNull();
    });
  });

  describe("the host's tool rows", () => {
    function renderFor(role: SeatRole, entries: StoryEntry[]) {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      return render(
        <QueryClientProvider client={client}>
          <I18nProvider language="en">
            <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role={role} campaignId={CAMPAIGN} />
          </I18nProvider>
        </QueryClientProvider>,
      );
    }

    it("show their dice while closed, and still open to the call (DEL-270)", () => {
      const roll = entry(1, "tool", {
        name: "roll",
        dice: [{ who: "Goblin", side: null, what: "hp", detail: null, dice: "2d8", faces: [3, 5], total: 8 }],
      });
      renderFor("host", [roll]);
      const row = screen.getByText("roll").closest("details")!;
      expect(row.open).toBe(false);
      expect(screen.getByRole("list", { name: "Dice" }).textContent?.trim()).toBe("Goblin, hit points — 2d8: 3, 5 (8)");
    });

    it("open to their call and reply, a batch step by step", async () => {
      const roll = entry(1, "tool", { name: "roll" });
      const batch = entry(3, "tool", { name: "batch" });
      const fetchMock = stubFetch({
        [`GET /api/campaigns/${CAMPAIGN}/story/${roll.id}/tool`]: () =>
          json(200, { name: "roll", args: { notation: "1d20" }, ok: true, result: { total: 12 } }),
        [`GET /api/campaigns/${CAMPAIGN}/story/${batch.id}/tool`]: () =>
          json(200, {
            name: "batch",
            args: { steps: [{ tool: "say", args: { npc: "Bollo", text: "Nothing but moor." } }, { tool: "advance_time", args: {} }] },
            ok: true,
            result: { results: [{ step: 0, tool: "say", result: { said: { text: "Nothing but moor." } } }, { step: 1, tool: "advance_time", error: "no" }] },
          }),
      });
      renderFor("host", [roll, entry(2, "dm_text", { text: "You hear nothing." }), batch]);
      expect(fetchMock).not.toHaveBeenCalled();

      const rollRow = screen.getByText("roll").closest("details")!;
      rollRow.open = true;
      fireEvent(rollRow, new Event("toggle"));
      expect(await within(rollRow).findByText(/"notation": "1d20"/)).toBeTruthy();
      expect(within(rollRow).getByText(/"total": 12/)).toBeTruthy();

      const batchRow = screen.getByText("batch").closest("details")!;
      batchRow.open = true;
      fireEvent(batchRow, new Event("toggle"));
      expect(await within(batchRow).findByText("say")).toBeTruthy();
      expect(within(batchRow).getByText("advance_time").parentElement!.textContent).toContain("refused");
      // The line is in the step's arguments and in its reply.
      expect(within(batchRow).getAllByText(/"text": "Nothing but moor."/, { selector: "pre" })).toHaveLength(2);
      vi.unstubAllGlobals();
    });

    it("stay closed rows for a co-host, who sees only the names", () => {
      renderFor("cohost", [entry(1, "tool", { name: "roll" })]);
      expect(screen.getByText("roll").closest("details")).toBeNull();
    });
  });

  describe("Retry (table voice and fixes Task D2)", () => {
    const BEAT = "beat_000000000002";
    const failed = (payload: Record<string, unknown> = {}, beat = BEAT) =>
      entry(2, "dm_error", { message: "The DM didn't answer: the DM provider failed", retryable: true, resets_at: null, ...payload } as StoryEntry["payload"], beat);

    function renderRetry(entries: StoryEntry[], state: { beat_id: string | null; may_retry: boolean; resets_at: string | null }) {
      const beatHandlers: ((data: unknown) => void)[] = [];
      const subscribe = (handlers: Record<string, (data: unknown) => void>) => {
        if (handlers.beat) beatHandlers.push(handlers.beat);
        return () => {};
      };
      const fetchMock = stubFetch({
        [`GET /api/campaigns/${CAMPAIGN}/retry`]: () => json(200, state),
        [`POST /api/campaigns/${CAMPAIGN}/beats/${BEAT}/retry`]: () => json(202, { beat: { id: BEAT, status: "running" } }),
      });
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={client}>
          <EventsContext.Provider value={subscribe}>
            <I18nProvider language="en">
              <Story entries={entries} hasMore={false} onLoadEarlier={() => {}} role="player" campaignId={CAMPAIGN} />
            </I18nProvider>
          </EventsContext.Provider>
        </QueryClientProvider>,
      );
      const beatEvent = (data: unknown) => act(() => beatHandlers.forEach((handle) => handle(data)));
      return { fetchMock, beatEvent };
    }

    it("shows Retry on the latest retryable error", async () => {
      const older = entry(1, "dm_error", { message: "The DM didn't answer: crash", retryable: true, resets_at: null } as StoryEntry["payload"], "beat_000000000001");
      const { fetchMock, beatEvent } = renderRetry([older, failed()], { beat_id: BEAT, may_retry: true, resets_at: null });
      const button = await screen.findByRole("button", { name: "Retry" });
      expect(screen.getAllByRole("button", { name: "Retry" })).toHaveLength(1);
      expect(button.textContent, "a retry arrow, named Retry").toBe("");
      expect(button.querySelector("svg")).not.toBeNull();
      expect(button.closest(".dm-error")?.textContent).toContain("the DM provider failed");
      fireEvent.click(button);
      expect(await screen.findByRole("button", { name: "Trying again…" })).toHaveProperty("disabled", true);
      expect(sent(fetchMock, "POST", `/api/campaigns/${CAMPAIGN}/beats/${BEAT}/retry`)).toEqual([{}]);
      // The beat's event lets it go: the retry state is asked again.
      const asked = () => fetchMock.mock.calls.filter(([p]) => p === `/api/campaigns/${CAMPAIGN}/retry`).length;
      const before = asked();
      beatEvent({ campaign_id: CAMPAIGN, beat_id: BEAT, status: "running" });
      await vi.waitFor(() => expect(asked()).toBeGreaterThan(before));
      expect(await screen.findByRole("button", { name: "Retry" })).toHaveProperty("disabled", false);
      vi.unstubAllGlobals();
    });

    it("hides it once retried", async () => {
      const { fetchMock } = renderRetry([failed({ retried: true })], { beat_id: BEAT, may_retry: true, resets_at: null });
      await Promise.resolve();
      expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
      // A retried error doesn't even ask.
      expect(fetchMock).not.toHaveBeenCalled();
      vi.unstubAllGlobals();
    });

    it("hides it for a newer beat", async () => {
      const { fetchMock } = renderRetry([failed()], { beat_id: "beat_000000000003", may_retry: false, resets_at: null });
      await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
      await Promise.resolve();
      expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
      vi.unstubAllGlobals();
    });

    it("hides it for an error from before retry existed", () => {
      const { fetchMock } = renderRetry([entry(2, "dm_error", { message: "The DM didn't answer: timeout" }, BEAT)], {
        beat_id: BEAT,
        may_retry: true,
        resets_at: null,
      });
      expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
      expect(fetchMock).not.toHaveBeenCalled();
      vi.unstubAllGlobals();
    });

    it("says when the limit ends", async () => {
      const at = new Date(Date.now() + 2 * 3600_000).toISOString();
      renderRetry([failed({ resets_at: at })], { beat_id: BEAT, may_retry: true, resets_at: at });
      const said = await screen.findByTestId("retry-resets");
      expect(said.textContent).toContain(`The usage limit ends at ${limitEnd(at, "en")}.`);
      vi.unstubAllGlobals();
    });

    it("names the day of a limit that ends another day", () => {
      const now = new Date("2026-10-25T10:00:00");
      expect(limitEnd("2026-10-25T14:50:00", "en", now)).not.toMatch(/Oct/);
      expect(limitEnd("2026-10-30T09:00:00", "en", now)).toMatch(/Oct/);
      expect(limitEnd("not a time", "en", now)).toBe("not a time");
    });
  });
});

describe("who acted", () => {
  it("is You for the seat's own act, and a hotseat player by name on the screen they share (DEL-365)", () => {
    const own = entry(1, "player_act", { seat_id: hostSeat.id, name: "Raf", text: "x" });
    const anna = entry(2, "player_act", { seat_id: hostSeat.id, name: "Anna", hotseat: "hs_anna", text: "x", characters: ["chr_a"] });
    expect(actor(own, hostSeat.id, {}, "You")).toBe("You");
    expect(actor(anna, hostSeat.id, { chr_a: "Garrek" }, "You")).toBe("Anna · Garrek");
    expect(actor(anna, "seat_00000000000b", {}, "You")).toBe("Anna");
  });
});
