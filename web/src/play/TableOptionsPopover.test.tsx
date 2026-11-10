import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import TableOptionsPopover from "./TableOptionsPopover";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "./testing";

const options = {
  tone: "classic",
  detail: 2,
  effort: null,
  model: null,
  beat_timer_s: null,
  fallback: "hold_back",
  paid_images: false,
  portrait_style: "illustrated",
  xp_awards: ["monsters", "milestones", "roleplay"],
};

afterEach(() => vi.unstubAllGlobals());

describe("TableOptionsPopover", () => {
  it("offers a custom tone, whose words are saved when the box is left (DEL-204)", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/play/options`]: () => json(200, { ...options, tone: "custom", custom_tone: "" }),
      [`PUT ${base}/play/options`]: (init) => json(200, { ...options, tone: "custom", ...JSON.parse(String(init?.body)) }),
    });
    renderWith(<TableOptionsPopover campaignId={CAMPAIGN} />);
    fireEvent.click(screen.getByRole("button", { name: "Table options" }));
    const box = await screen.findByTestId("custom-tone");
    fireEvent.change(box, { target: { value: " Keep it light; no gore. " } });
    expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([]);
    fireEvent.blur(box);
    await waitFor(() =>
      // Only the words: the tone is already custom (DEL-168).
      expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ custom_tone: "Keep it light; no gore." }]),
    );
  });

  it("puts the enemies' dice behind the screen or in the open, saved at once (DEL-270)", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/play/options`]: () => json(200, { ...options, enemy_dice: "screen" }),
      [`PUT ${base}/play/options`]: (init) => json(200, { ...options, ...JSON.parse(String(init?.body)) }),
    });
    renderWith(<TableOptionsPopover campaignId={CAMPAIGN} />);
    fireEvent.click(screen.getByRole("button", { name: "Table options" }));
    const select = (await screen.findByRole("combobox", { name: "Enemies' dice" })) as HTMLSelectElement;
    expect(select.value).toBe("screen");
    expect([...select.options].map((o) => o.textContent)).toEqual(["Behind the screen", "In the open"]);
    expect(select.getAttribute("aria-describedby")).toBe("play-enemy-dice-hint");
    fireEvent.change(select, { target: { value: "open" } });
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ enemy_dice: "open" }]));
    expect(select.value).toBe("open");
  });

  it("hides the dice from the story for the other seats, and with them the enemies' choice (DEL-280)", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/play/options`]: () => json(200, { ...options, enemy_dice: "screen", show_dice: true }),
      [`PUT ${base}/play/options`]: (init) => json(200, { ...options, enemy_dice: "screen", ...JSON.parse(String(init?.body)) }),
    });
    renderWith(<TableOptionsPopover campaignId={CAMPAIGN} />);
    fireEvent.click(screen.getByRole("button", { name: "Table options" }));
    const box = (await screen.findByRole("checkbox", { name: "Dice in the story" })) as HTMLInputElement;
    const enemies = screen.getByRole("combobox", { name: "Enemies' dice" }) as HTMLSelectElement;
    expect([box.checked, enemies.disabled]).toEqual([true, false]);
    fireEvent.click(box);
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ show_dice: false }]));
    expect([box.checked, enemies.disabled]).toEqual([false, true]);
  });

  it("allows pictures in table talk, saved at once (DEL-294)", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/play/options`]: () => json(200, { ...options, talk_pictures: false }),
      [`PUT ${base}/play/options`]: (init) => json(200, { ...options, ...JSON.parse(String(init?.body)) }),
    });
    renderWith(<TableOptionsPopover campaignId={CAMPAIGN} />);
    fireEvent.click(screen.getByRole("button", { name: "Table options" }));
    const box = (await screen.findByRole("checkbox", { name: "Pictures in table talk" })) as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ talk_pictures: true }]));
    expect(box.checked).toBe(true);
  });

  it("ticks what earns XP, and saves a box at once (DEL-113), two quick ticks both kept (DEL-168)", async () => {
    // The server applies each body to what it has, as `PUT …/play/options` does.
    let stored: Record<string, unknown> = { ...options };
    const fetchMock = stubFetch({
      [`GET ${base}/play/options`]: () => json(200, stored),
      [`PUT ${base}/play/options`]: (init) => json(200, (stored = { ...stored, ...JSON.parse(String(init?.body)) })),
    });
    renderWith(<TableOptionsPopover campaignId={CAMPAIGN} />);
    fireEvent.click(screen.getByRole("button", { name: "Table options" }));
    const awards = await screen.findByTestId("xp-awards");
    const box = (name: string) => within(awards).getByRole("checkbox", { name: new RegExp(name) }) as HTMLInputElement;
    expect(["Monsters", "Story milestones", "Roleplaying", "Gold", "Ability use"].map((n) => box(n).checked)).toEqual([
      true,
      true,
      true,
      false,
      false,
    ]);

    // The second tick before the first is saved (the boxes no longer wait for it): neither undoes the other.
    fireEvent.click(box("Gold"));
    fireEvent.click(box("Roleplaying"));
    await waitFor(() => expect([box("Gold").checked, box("Roleplaying").checked]).toEqual([true, false]));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toHaveLength(2));
    expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([
      { xp_awards: ["monsters", "milestones", "roleplay", "gold"] },
      { xp_awards: ["monsters", "milestones", "gold"] },
    ]);
    await waitFor(() => expect(box("Gold").checked && !box("Roleplaying").checked).toBe(true));
    expect(stored.xp_awards).toEqual(["monsters", "milestones", "gold"]);
  });

  it("sends only the option changed, never the beat timer with it (DEL-168)", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/play/options`]: () => json(200, { ...options, beat_timer_s: 120, effort: "high" }),
      [`PUT ${base}/play/options`]: (init) => json(200, { ...options, beat_timer_s: 120, ...JSON.parse(String(init?.body)) }),
    });
    renderWith(<TableOptionsPopover campaignId={CAMPAIGN} />);
    fireEvent.click(screen.getByRole("button", { name: "Table options" }));
    fireEvent.change(await screen.findByLabelText("Tone"), { target: { value: "horror" } });
    fireEvent.change(screen.getByLabelText("Effort"), { target: { value: "" } });
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toHaveLength(2));
    // Back to the Preferences choice is a null effort, which the server stores as none.
    expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ tone: "horror" }, { effort: null }]);
  });
});
