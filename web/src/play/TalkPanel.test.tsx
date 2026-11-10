import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { LIMITS } from "./limits";
import TalkPanel, { quoteOf } from "./TalkPanel";
import { entry, hostSeat, seat } from "./testing";

const ANA = "seat_00000000000a";

afterEach(() => vi.unstubAllGlobals());

describe("TalkPanel", () => {
  it("shows table talk, in the seat's language when translated, and a shared answer", () => {
    const talk = [
      { ...entry(1, "talk", { seat_id: ANA, name: "Ana", text: "Shall we rest?", original: "Zullen we rusten?", language: "nl" }, ""), beat_id: null },
      {
        ...entry(2, "talk", { seat_id: hostSeat.id, name: "Raf", text: "Not yet." }, ""),
        beat_id: null,
        translation: { language: "nl", text: "Nog niet.", status: "done" as const },
      },
      {
        ...entry(3, "talk", { seat_id: ANA, name: "Ana", text: "What's a kobold?", answer: "A small dog-like humanoid.", shared: "ste_000000000009" }, ""),
        beat_id: null,
      },
    ];
    render(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    const panel = screen.getByTestId("talk-panel");
    expect(within(panel).getByText("Shall we rest?")).toBeTruthy();
    expect(within(panel).getByText("Nog niet."), "the translation, not the English").toBeTruthy();
    expect(within(panel).queryByText("Not yet.")).toBeNull();
    expect(within(panel).getByText("You")).toBeTruthy();
    expect(within(panel).getAllByText("Ana")).toHaveLength(2);
    const shared = within(panel).getByText("A small dog-like humanoid.").closest("li")!;
    expect(shared.textContent).toContain("What's a kobold?");
    expect(shared.textContent).toContain("The DM answered");
  });

  it("shows a shared answer in the seat's language once translated (plan 7 Task 18)", () => {
    const shared = {
      ...entry(3, "talk", { seat_id: ANA, name: "Ana", text: "What's a kobold?", answer: "A small humanoid.", shared: "ste_9" }, ""),
      beat_id: null,
      translation: { language: "nl", text: "Wat is een kobold?", status: "done" as const, answer: "NL: A small humanoid." },
    };
    render(
      <I18nProvider language="nl">
        <TalkPanel entries={[shared]} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    const panel = screen.getByTestId("talk-panel");
    expect(within(panel).getByText("Wat is een kobold?")).toBeTruthy();
    expect(within(panel).getByText("NL: A small humanoid.")).toBeTruthy();
    expect(within(panel).queryByText("A small humanoid.")).toBeNull();
  });

  // Walkthrough T3: the shared answer was a one-line preview with raw `**`.
  it("renders a shared answer's Markdown, clipped to three lines with Show all", () => {
    const answer = "**Turn undead:** roll 1d20.\n\n<b>raw</b>\n\n- a 7 or more turns a skeleton";
    const talk = [{ ...entry(1, "talk", { seat_id: ANA, name: "Ana", text: "How do I turn?", answer, shared: "ste_000000000009" }, ""), beat_id: null }];
    render(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    const shared = screen.getByTestId("talk-panel").querySelector(".talk-answer-text")!;
    expect(shared.querySelector("strong")?.textContent).toBe("Turn undead:");
    expect(shared.querySelector("b"), "escaped, as everywhere").toBeNull();
    expect(shared.textContent).not.toContain("**");
    expect(shared.classList.contains("clipped")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Show all" }));
    expect(shared.classList.contains("clipped")).toBe(false);
    expect(screen.queryByRole("button", { name: "Show all" })).toBeNull();
  });

  it("says when nobody has talked yet", () => {
    render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    expect(screen.getByTestId("talk-panel").textContent).toContain("Nobody has said anything");
  });

  it("has its own box: Enter sends to the table, Shift-Enter starts a new line", () => {
    const onTalk = vi.fn();
    render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} onTalk={onTalk} />
      </I18nProvider>,
    );
    const box = within(screen.getByTestId("talk-box")).getByRole("textbox") as HTMLTextAreaElement;
    expect(box.getAttribute("placeholder")).toBe("Talk to the table");
    fireEvent.change(box, { target: { value: "Hello, all" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onTalk).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onTalk).toHaveBeenCalledWith("Hello, all");
    expect(box.value).toBe("");
  });

  it("puts emoji where the cursor is, and a quoted line at the top of the box", () => {
    const talk = [{ ...entry(1, "talk", { seat_id: ANA, name: "Mira", text: "North road?" }, ""), beat_id: null }];
    render(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} onTalk={vi.fn()} />
      </I18nProvider>,
    );
    const box = within(screen.getByTestId("talk-box")).getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "cheers" } });
    box.setSelectionRange(6, 6);
    fireEvent.click(screen.getByTestId("emoji"));
    fireEvent.click(screen.getByRole("button", { name: "🍺" }));
    expect(box.value).toBe("cheers🍺");
    fireEvent.click(screen.getByTestId("talk-quote-button"));
    expect(box.value).toBe("> Mira: North road?\ncheers🍺");
  });

  it("sends nothing past the talk's length", () => {
    const onTalk = vi.fn();
    render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} onTalk={onTalk} />
      </I18nProvider>,
    );
    const box = within(screen.getByTestId("talk-box")).getByRole("textbox");
    fireEvent.change(box, { target: { value: "x".repeat(LIMITS.talk + 1) } });
    expect((screen.getByTestId("talk") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("talk-count").className).toContain("over");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onTalk).not.toHaveBeenCalled();
  });

  it("says who is typing", () => {
    render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} onTalk={vi.fn()} seats={[hostSeat, seat(ANA, "Ana")]}
          typing={{ [ANA]: "typing", [hostSeat.id]: "typing" }} />
      </I18nProvider>,
    );
    expect(screen.getByTestId("talk-box").textContent).toContain("Ana is typing");
  });

  it("folds to one line that counts the lines since, and unfolds", () => {
    const first = { ...entry(1, "talk", { seat_id: ANA, name: "Ana", text: "Shall we rest?" }, ""), beat_id: null };
    const next = { ...entry(2, "talk", { seat_id: ANA, name: "Ana", text: "The strings moved." }, ""), beat_id: null };
    const mine = { ...entry(3, "talk", { seat_id: hostSeat.id, name: "Raf", text: "I saw." }, ""), beat_id: null };
    const { rerender } = render(
      <I18nProvider language="en">
        <TalkPanel entries={[first]} mySeatId={hostSeat.id} foldable />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByTestId("talk-fold"));
    expect(screen.queryByTestId("talk-new"), "nothing new yet").toBeNull();
    rerender(
      <I18nProvider language="en">
        <TalkPanel entries={[first, next, mine]} mySeatId={hostSeat.id} foldable />
      </I18nProvider>,
    );
    expect(screen.getByTestId("talk-new").textContent, "the seat's own line doesn't count").toBe("1 new");
    expect(screen.getByTestId("talk-unfold").textContent).toContain("Ana: The strings moved.");
    fireEvent.click(screen.getByTestId("talk-unfold"));
    expect(screen.getByText("I saw.")).toBeTruthy();
  });

  it("raises a hand with a point, and lowers it once it is up", () => {
    const onRaise = vi.fn();
    const onLower = vi.fn();
    const { rerender } = render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} hand={{ mine: undefined, onRaise, onLower }} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByTestId("raise-hand"));
    fireEvent.change(screen.getByLabelText("Your point, before anyone acts (optional)"), { target: { value: " Her shadow is missing " } });
    fireEvent.click(screen.getByTestId("raise-hand-confirm"));
    expect(onRaise).toHaveBeenCalledWith("Her shadow is missing");
    rerender(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} hand={{ mine: { seat_id: hostSeat.id, at: "", point: null }, onRaise, onLower }} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByTestId("lower-hand"));
    expect(onLower).toHaveBeenCalled();
  });

  it("says idle when the box goes while words are being typed", () => {
    const onTyping = vi.fn();
    const { unmount } = render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} onTalk={vi.fn()} onTyping={onTyping} />
      </I18nProvider>,
    );
    fireEvent.change(within(screen.getByTestId("talk-box")).getByRole("textbox"), { target: { value: "Shall w" } });
    expect(onTyping).toHaveBeenLastCalledWith("typing");
    unmount();
    expect(onTyping).toHaveBeenLastCalledWith("idle");
  });

  it("widens and narrows, and has no box without onTalk", () => {
    const onWiden = vi.fn();
    render(
      <I18nProvider language="en">
        <TalkPanel entries={[]} mySeatId={hostSeat.id} wide onWiden={onWiden} />
      </I18nProvider>,
    );
    const button = screen.getByTestId("talk-widen");
    expect(button.getAttribute("aria-label")).toBe("Narrow the talk");
    fireEvent.click(button);
    expect(onWiden).toHaveBeenCalled();
    expect(screen.queryByTestId("talk-box")).toBeNull();
  });

  it("a line shows its speaker's avatar and colour", () => {
    const profile = { account_id: "acc_00000000000a", display_name: "Ana", pronouns: "", avatar: { emblem: "stag" }, colour: "ember" };
    const talk = [
      { ...entry(1, "talk", { seat_id: ANA, name: "Ana", text: "Hello." }, ""), beat_id: null },
      { ...entry(2, "talk", { seat_id: hostSeat.id, name: "Raf", text: "Welcome." }, ""), beat_id: null },
      { ...entry(3, "talk", { seat_id: "seat_00000000000z", name: "Zed", text: "Bye." }, ""), beat_id: null },
    ];
    render(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} seats={[hostSeat, seat(ANA, "Ana", { profile })]} />
      </I18nProvider>,
    );
    const line = (id: string) => screen.getByTestId("talk-panel").querySelector<HTMLElement>(`li[data-seat="${id}"]`)!;
    const ana = line(ANA);
    expect(ana.dataset.colour).toBe("ember");
    expect(ana.style.getPropertyValue("--talk-colour")).toBe("#e08a3c");
    expect(ana.querySelector(".avatar")?.getAttribute("data-emblem")).toBe("stag");
    const initial = line(hostSeat.id).querySelector(".avatar-initial");
    expect(initial?.textContent, "the owner's seat has no profile: its name's first letter").toBe(hostSeat.name[0].toUpperCase());
    const gone = line("seat_00000000000z");
    expect(gone.querySelector(".avatar"), "a seat that left: the name alone").toBeNull();
    expect(gone.textContent).toContain("Zed");
  });
});

describe("TalkList as a chat", () => {
  const at = (minute: number) => `2026-10-26T08:${String(minute).padStart(2, "0")}:00+00:00`;
  const line = (n: number, seat: string, name: string, text: string, minute: number) => ({
    ...entry(n, "talk", { seat_id: seat, name, text }, ""),
    beat_id: null,
    at: at(minute),
  });

  it("runs a speaker's lines together, shows a quote apart, and quotes a line", () => {
    const talk = [
      line(1, ANA, "Ana", "Evening!", 1),
      line(2, ANA, "Ana", "Dice ready.", 2),
      line(3, hostSeat.id, "Raf", "> Ana: Dice ready.\nGood, we start.", 3),
      line(4, ANA, "Ana", "Later on.", 30),
    ];
    render(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    const lines = [...screen.getByTestId("talk-panel").querySelectorAll<HTMLElement>("li.talk")];
    expect(lines.map((l) => l.classList.contains("run"))).toEqual([false, true, false, false]);
    expect(lines[1].querySelector(".talk-who")).toBeNull();
    expect(within(lines[2]).getByTestId("talk-quote").textContent).toBe("Ana: Dice ready.");
    expect(lines[2].querySelector(".talk-text")?.textContent).toBe("Good, we start.");
    expect(lines[0].querySelector("time")?.getAttribute("dateTime")).toBe(at(1));
    expect(quoteOf("Ana", "Dice ready.")).toBe("> Ana: Dice ready.");
  });

  it("loads its earlier lines with Load earlier, and when scrolled to its top (DEL-219)", () => {
    const talk = [{ ...entry(70, "talk", { seat_id: ANA, name: "Ana", text: "Torches out." }, ""), beat_id: null }];
    const onLoadEarlier = vi.fn();
    const { rerender } = render(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} hasMore onLoadEarlier={onLoadEarlier} />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByTestId("talk-earlier"));
    expect(onLoadEarlier).toHaveBeenCalledTimes(1);
    const list = screen.getByRole("list", { name: "Table talk" });
    list.scrollTop = 0;
    fireEvent.scroll(list);
    expect(onLoadEarlier).toHaveBeenCalledTimes(2);

    rerender(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} hasMore loadingEarlier onLoadEarlier={onLoadEarlier} />
      </I18nProvider>,
    );
    fireEvent.scroll(list);
    expect(onLoadEarlier, "never twice at once").toHaveBeenCalledTimes(2);
    rerender(
      <I18nProvider language="en">
        <TalkPanel entries={talk} mySeatId={hostSeat.id} onLoadEarlier={onLoadEarlier} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId("talk-earlier"), "nothing earlier").toBeNull();
  });

  describe("pictures (DEL-294)", () => {
    const picture = { blob: "ab".repeat(32), mime: "image/webp", width: 300, height: 200 };
    const pasted = { ...entry(4, "talk", { seat_id: ANA, name: "Ana", text: "", picture }, ""), beat_id: null };

    function renderTalk(props: Partial<Parameters<typeof TalkPanel>[0]> = {}) {
      render(
        <I18nProvider language="en">
          <TalkPanel entries={[pasted]} mySeatId={hostSeat.id} onTalk={() => {}} pictureUrl={(id) => `/pictures/${id}`} {...props} />
        </I18nProvider>,
      );
    }

    it("shows a pasted picture, which opens enlarged", () => {
      renderTalk();
      const open = screen.getByRole("button", { name: "Enlarge: a picture from Ana" });
      expect(within(open).getByRole("img").getAttribute("src")).toBe(`/pictures/${pasted.id}`);
      fireEvent.click(open);
      expect(within(screen.getByRole("dialog")).getByRole("img").getAttribute("src")).toBe(`/pictures/${pasted.id}`);
    });

    it("takes a picture down for who may, and says so once it is", () => {
      const onTakeDown = vi.fn();
      renderTalk({ onTakeDown, mayTakeDown: () => true });
      fireEvent.click(screen.getByRole("button", { name: "Take Ana's picture down" }));
      expect(onTakeDown).toHaveBeenCalledWith(pasted.id);
    });

    it("offers no Take down to anyone else, and shows a picture taken down", () => {
      const gone = { ...pasted, id: "ste_000000000005", payload: { seat_id: ANA, name: "Ana", text: "", picture_removed: true } };
      renderTalk({ entries: [pasted, gone], onTakeDown: vi.fn(), mayTakeDown: () => false });
      expect(screen.queryByRole("button", { name: /picture down/ })).toBeNull();
      expect(screen.getByText("Picture taken down")).toBeTruthy();
    });

    it("sends a picture pasted into the box, or picked, while pictures are allowed", () => {
      const onPicture = vi.fn();
      renderTalk({ onPicture });
      const file = new File([new Uint8Array([137, 80, 78, 71])], "shot.png", { type: "image/png" });
      fireEvent.paste(screen.getByLabelText(/^Table talk:/), { clipboardData: { files: [file], items: [], types: ["Files"] } });
      expect(onPicture).toHaveBeenCalledWith(file);
      const other = new File([new Uint8Array([1])], "map.jpg", { type: "image/jpeg" });
      fireEvent.change(screen.getByLabelText("Add a picture"), { target: { files: [other] } });
      expect(onPicture).toHaveBeenLastCalledWith(other);
    });

    it("lets words be pasted as words, and has no picture button while pictures aren't allowed", () => {
      renderTalk();
      expect(screen.queryByLabelText("Add a picture")).toBeNull();
      const box = screen.getByLabelText(/^Table talk:/);
      expect(fireEvent.paste(box, { clipboardData: { files: [], items: [], types: ["text/plain"] } })).toBe(true);
    });
  });
});
