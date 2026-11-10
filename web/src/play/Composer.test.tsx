import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Composer from "./Composer";
import { LIMITS } from "./limits";
import { renderWith } from "./testing";

const party = [
  { id: "a", name: "Ash" },
  { id: "b", name: "Birch" },
  { id: "c", name: "Cedar" },
];

function composer(onAct = vi.fn()) {
  renderWith(<Composer running={false} asking={false} error={null} characters={party} onAct={onAct} onAsk={vi.fn()} onCancel={vi.fn()} />);
  return onAct;
}

function act(text = "We push on") {
  const box = within(screen.getByTestId("composer")).getByRole("textbox");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
}

const forButton = () => screen.getByTestId("act-for");

describe("Composer: acting for", () => {
  it("acts for the whole party by default, with the ticks out of sight", () => {
    const onAct = composer();
    expect(forButton().textContent).toContain("Acting for: whole party");
    expect(screen.queryByRole("checkbox", { name: "Birch" })).toBeNull();
    act();
    expect(onAct).toHaveBeenCalledWith("We push on", undefined, undefined);
  });

  it("picks one character in one click, and the button says who", () => {
    const onAct = composer();
    fireEvent.click(forButton());
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Birch" }));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(forButton().textContent).toContain("Acting for: Birch");
    act();
    expect(onAct).toHaveBeenCalledWith("We push on", ["b"], undefined);
  });

  it("goes back to the whole party", () => {
    const onAct = composer();
    fireEvent.click(forButton());
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Birch" }));
    fireEvent.click(forButton());
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Whole party" }));
    expect(forButton().textContent).toContain("Acting for: whole party");
    act();
    expect(onAct).toHaveBeenCalledWith("We push on", undefined, undefined);
  });

  it("ticks several under Several…, and counts them", () => {
    const onAct = composer();
    fireEvent.click(forButton());
    fireEvent.click(screen.getByRole("menuitem", { name: "Several…" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Birch" }));
    expect(forButton().textContent).toContain("Acting for: 2 of 3");
    act();
    expect(onAct).toHaveBeenCalledWith("We push on", ["a", "c"], undefined);
  });

  it("closes the menu with Escape", () => {
    composer();
    fireEvent.click(forButton());
    expect(screen.getByRole("menu")).toBeTruthy();
    fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("acting for leaves the departed out", () => {
    const onAct = vi.fn();
    const departed = [...party, { id: "d", name: "Tansy", departure: "died" as const }];
    renderWith(<Composer running={false} asking={false} error={null} characters={departed} onAct={onAct} onAsk={vi.fn()} onCancel={vi.fn()} />);
    fireEvent.click(forButton());
    expect(screen.queryByRole("menuitemradio", { name: "Tansy" })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Several…" }));
    expect(screen.queryByRole("checkbox", { name: "Tansy" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Birch" }));
    expect(forButton().textContent).toContain("Acting for: 2 of 3");
    act();
    expect(onAct).toHaveBeenCalledWith("We push on", ["a", "c"], undefined);
  });

  it("shows no choice for a seat with one character", () => {
    render(
      <Composer running={false} asking={false} error={null} characters={[party[0]]} onAct={vi.fn()} onAsk={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.queryByTestId("act-for")).toBeNull();
  });
});

describe("Composer: it speaks to the DM (DEL-199)", () => {
  const box = () => within(screen.getByTestId("composer")).getByRole("textbox") as HTMLTextAreaElement;
  const props = { running: false, asking: false, error: null, onAct: vi.fn(), onAsk: vi.fn(), onCancel: vi.fn() };

  it("says where Enter sends the words, and wears that channel; table talk has its own box", () => {
    renderWith(<Composer {...props} />);
    expect(screen.getByTestId("composer").dataset.channel).toBe("act");
    expect(screen.getByTestId("composer-channel").textContent).toContain("To the DM");
    expect(screen.queryByTestId("talk"), "no Table talk here").toBeNull();
    expect(screen.queryByTestId("emoji")).toBeNull();
    fireEvent.click(screen.getByTestId("mode-ask"));
    expect(screen.getByTestId("composer").dataset.channel).toBe("ask");
  });

  it("while the DM answers, Act waits and the words stay in the box", () => {
    const onAct = vi.fn();
    const { rerender } = renderWith(<Composer {...props} running characters={party} onAct={onAct} />);
    expect((screen.getByTestId("act") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("composer-hint").textContent).toBe("You can act again when the DM is done. Your words stay here.");
    fireEvent.change(box(), { target: { value: "We go on" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onAct).not.toHaveBeenCalled();
    expect(box().value).toBe("We go on");

    // The DM is done: Enter acts again.
    rerender(<Composer {...props} running={false} characters={party} onAct={onAct} />);
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onAct).toHaveBeenCalledWith("We go on", undefined, undefined);
  });

  it("Act waits, with the reason, while the session hasn't started; asking still works", () => {
    const onAct = vi.fn();
    const onAsk = vi.fn();
    renderWith(<Composer {...props} onAct={onAct} onAsk={onAsk} blocked="You can act once the host starts the session." />);
    expect((screen.getByTestId("act") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("composer-hint").textContent).toBe("You can act once the host starts the session.");
    fireEvent.change(box(), { target: { value: "What's in the wagon?" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onAct).not.toHaveBeenCalled();
    fireEvent.keyDown(box(), { key: "Enter", ctrlKey: true });
    expect(onAsk).toHaveBeenCalledWith("What's in the wagon?");
  });

  it("an observer only asks", () => {
    const onAsk = vi.fn();
    renderWith(<Composer {...props} canAct={false} onAsk={onAsk} />);
    expect(screen.queryByTestId("mode-own")).toBeNull();
    expect(screen.queryByTestId("act")).toBeNull();
    expect(screen.getByTestId("composer").dataset.channel).toBe("ask");
    fireEvent.change(box(), { target: { value: "Who rules here?" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onAsk).toHaveBeenCalledWith("Who rules here?");
  });

  it("shows its notice above the buttons", () => {
    renderWith(<Composer {...props} notice={<p data-testid="a-notice">Joren has a hand up.</p>} />);
    expect(screen.getByTestId("a-notice")).toBeTruthy();
  });
});

describe("Composer: how long (DEL-154)", () => {
  const box = () => within(screen.getByTestId("composer")).getByRole("textbox") as HTMLTextAreaElement;
  const props = { running: false, asking: false, error: null, onAct: vi.fn(), onAsk: vi.fn(), onCancel: vi.fn() };

  it("takes as many characters as its channel's length, and counts down near it", () => {
    renderWith(<Composer {...props} />);
    expect(box().maxLength).toBe(LIMITS.act);
    expect(screen.queryByTestId("composer-count")).toBeNull();
    fireEvent.change(box(), { target: { value: "x".repeat(LIMITS.act - 100) } });
    expect(screen.getByTestId("composer-count").textContent).toBe(`${LIMITS.act - 100} / ${LIMITS.act}`);
    fireEvent.click(screen.getByTestId("mode-ask"));
    expect(box().maxLength).toBe(LIMITS.ask);
  });

  it("sends nothing past the length: the words stay to be cut", () => {
    const onAct = vi.fn();
    renderWith(<Composer {...props} onAct={onAct} />);
    fireEvent.change(box(), { target: { value: "x".repeat(LIMITS.act + 1) } });
    expect(screen.getByTestId("composer-count").className).toContain("over");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onAct).not.toHaveBeenCalled();
    expect(box().value).toHaveLength(LIMITS.act + 1);
  });
});

describe("Composer: typing", () => {
  it("says idle when it goes while words are being typed", () => {
    const onTyping = vi.fn();
    const { unmount } = render(
      <Composer running={false} asking={false} error={null} characters={party} onAct={vi.fn()} onAsk={vi.fn()} onCancel={vi.fn()} onTyping={onTyping} />,
    );
    fireEvent.change(within(screen.getByTestId("composer")).getByRole("textbox"), { target: { value: "We pu" } });
    expect(onTyping).toHaveBeenLastCalledWith("typing");
    unmount();
    expect(onTyping).toHaveBeenLastCalledWith("idle");
  });
});
