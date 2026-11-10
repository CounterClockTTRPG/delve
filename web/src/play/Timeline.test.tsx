import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Timeline from "./Timeline";
import type { TimelineFight, TimelineSlot } from "./timeline";
import { CAMPAIGN, FakeEventSource, base, json, renderWith, stubFetch } from "./testing";

beforeEach(() => {
  localStorage.clear();
  FakeEventSource.open = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

function slot(key: string, name: string | null, count: number | null, overrides: Partial<TimelineSlot> = {}): TimelineSlot {
  const side = key.startsWith("chr_") ? "party" : "enemy";
  return { key, name, side, character_id: side === "party" ? key : null, count, state: "waiting", ongoing: null, ...overrides };
}

const sleep = { kind: "spell", what: "Sleep", from: 1, to: 7, next_round: false, state: "ongoing", reason: null } as const;

function fight(overrides: Partial<TimelineFight> = {}): TimelineFight {
  return {
    combat_id: "cbt_000000000001",
    round: 1,
    mode: "combatant",
    released: false,
    max_count: 10,
    slots: [
      slot("chr_00000000000a", "Mirela", 7, { ongoing: sleep }),
      slot("chr_00000000000b", "Tansy", 4),
      slot("mon_1", "Goblin 1", 4),
    ],
    ...overrides,
  };
}

function serve(...answers: (TimelineFight | null)[]) {
  let i = 0;
  return stubFetch({
    [`GET ${base}/timeline`]: () => json(200, { fight: answers[Math.min(i++, answers.length - 1)] }),
  });
}

async function strip(phone = false) {
  renderWith(<Timeline campaignId={CAMPAIGN} phone={phone} />);
  return screen.findByTestId("timeline");
}

describe("Timeline", () => {
  it("renders nothing without a fight", async () => {
    const fetchMock = serve(null);
    const { container } = renderWith(<Timeline campaignId={CAMPAIGN} phone={false} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container.querySelector("[data-testid=timeline]")).toBeNull();
  });

  it("shows the round and stacks two slots on one count", async () => {
    serve(fight());
    const shown = await strip();
    expect(shown.textContent).toContain("Round 1");
    const four = within(shown).getByLabelText("Count 4");
    expect(within(four).getByText("Tansy")).toBeTruthy();
    expect(within(four).getByText("Goblin 1")).toBeTruthy();
    expect(within(shown).getByLabelText("Count 7").textContent).toContain("Mirela");
  });

  it("raises the names of every other neighbouring count", async () => {
    serve(fight({ slots: [slot("mon_1", "Goblin 1", 4), slot("mon_2", "Goblin 2", 5), slot("mon_3", "Goblin 3", 6), slot("mon_4", "Goblin 4", 9)] }));
    const shown = await strip();
    const raisedCounts = [...shown.querySelectorAll<HTMLElement>("[data-raised]")].map((g) => g.dataset.count);
    expect(raisedCounts).toEqual(["5"]);
  });

  it("draws a span to its count", async () => {
    serve(fight());
    const span = (await strip()).querySelector<HTMLElement>("[data-testid=timeline-span-chr_00000000000a]")!;
    expect([span.dataset.from, span.dataset.to]).toEqual(["1", "7"]);
    // Its row runs to the axis's end (10), its bar over counts 1 to 7: 7 of 10.
    expect(span.style.gridColumn).toBe("1 / 11");
    expect(span.style.getPropertyValue("--covered")).toBe("70%");
    expect(span.textContent).toContain("casting Sleep");
    expect(span.querySelector("em")!.textContent).toBe("Sleep");
    expect(span.textContent).toContain("until 7");
  });

  it("runs a long span off the end", async () => {
    serve(fight({ max_count: 12, slots: [slot("chr_00000000000a", "Mirela", 3, { ongoing: { ...sleep, to: 10, next_round: true } })] }));
    const span = (await strip()).querySelector<HTMLElement>("[data-testid=timeline-span-chr_00000000000a]")!;
    expect(span.style.gridColumn).toBe("1 / 13");
    expect(span.style.getPropertyValue("--covered")).toBe("100%");
    expect(span.dataset.nextRound).toBe("true");
    expect(span.textContent).toContain("next round");
  });

  it("marks interrupted, and who acted, once the round is told", async () => {
    const told = fight({
      released: true,
      slots: [
        slot("chr_00000000000a", "Mirela", 7, { state: "acted", ongoing: { ...sleep, state: "interrupted", reason: "Mirela was hit" } }),
        slot("mon_1", "Goblin 1", 4, { state: "dead" }),
        slot("mon_2", "Goblin 2", null, { state: "down" }),
      ],
    });
    serve(told);
    const shown = await strip();
    const span = shown.querySelector<HTMLElement>("[data-testid=timeline-span-chr_00000000000a]")!;
    expect(span.dataset.state).toBe("interrupted");
    expect(span.textContent).toContain("interrupted: Mirela was hit");
    expect(shown.querySelector("[data-testid=timeline-slot-mon_1]")!.textContent).toContain("dead");
    expect(within(shown).getByLabelText("Out of the round").textContent).toContain("Goblin 2");
  });

  it("unseen enemy shows no name, and an enemy's spell only its kind", async () => {
    serve(
      fight({
        slots: [
          slot("unseen-1", null, 5),
          slot("mon_1", "Goblin 1", 6, { ongoing: { ...sleep, what: null, to: 9 } }),
        ],
      }),
    );
    const shown = await strip();
    expect(shown.querySelector("[data-testid=timeline-slot-unseen-1]")!.textContent).toContain("Unseen");
    const span = shown.querySelector("[data-testid=timeline-span-mon_1]")!;
    expect(span.textContent).toContain("casting a spell");
    expect(span.querySelector("em")).toBeNull();
  });

  it("phone row scrolls sideways: one row of the counts in order", async () => {
    serve(fight());
    const shown = await strip(true);
    const row = shown.querySelector<HTMLElement>("[data-layout=row]")!;
    expect(row).toBeTruthy();
    expect(shown.querySelector("[data-layout=axis]")).toBeNull();
    const counts = [...row.querySelectorAll<HTMLElement>("[data-count]")].map((c) => c.dataset.count);
    expect(counts).toEqual(["4", "7"]);
    expect(row.textContent).toContain("casting Sleep · until 7");
  });

  it("reads the timeline again on its event, for its own campaign only", async () => {
    const fetchMock = serve(null, fight());
    renderWith(<Timeline campaignId={CAMPAIGN} phone={false} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    FakeEventSource.emit("timeline", { campaign_id: "cmp_00000000000z", change: "initiative" });
    FakeEventSource.emit("timeline", { campaign_id: CAMPAIGN, combat_id: "cbt_000000000001", round: 1, change: "initiative" });
    expect(await screen.findByTestId("timeline")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("folds to one line and opens again, remembered (DEL-130)", async () => {
    serve(fight());
    const shown = await strip();
    fireEvent.click(within(shown).getByRole("button", { name: "Fold the initiative" }));
    expect(shown.querySelector("[data-layout=axis] ol, [aria-label='Count 4']")).toBeNull();
    expect(shown.textContent).toContain("Round 1");
    expect(localStorage.getItem("delve.timeline.folded")).toBe("1");
    fireEvent.click(within(shown).getByRole("button", { name: "Show the initiative" }));
    expect(within(shown).getByLabelText("Count 4")).toBeTruthy();
  });

  it("folds on a phone too", async () => {
    localStorage.setItem("delve.timeline.folded", "1");
    serve(fight());
    const shown = await strip(true);
    expect(within(shown).queryByText("Tansy")).toBeNull();
    expect(within(shown).getByRole("button", { name: "Show the initiative" })).toBeTruthy();
  });

  it("hides enemies who are down, dead or fled, but never the party (DEL-130)", async () => {
    serve(
      fight({
        slots: [
          slot("chr_00000000000b", "Tansy", null, { state: "down" }),
          slot("mon_1", "Goblin 1", 4),
          slot("mon_2", "Goblin 2", 5, { state: "dead" }),
          slot("mon_3", "Goblin 3", null, { state: "dead" }),
          slot("mon_4", "Goblin 4", null, { state: "fled" }),
        ],
      }),
    );
    const shown = await strip();
    expect(within(shown).getByText("Goblin 3")).toBeTruthy();
    const hide = within(shown).getByRole("button", { name: /Hide enemies out of the fight/ });
    fireEvent.click(hide);
    expect(hide.getAttribute("aria-pressed")).toBe("true");
    for (const gone of ["Goblin 2", "Goblin 3", "Goblin 4"]) expect(within(shown).queryByText(gone)).toBeNull();
    expect(within(shown).getByText("Goblin 1")).toBeTruthy();
    expect(within(shown).getByText("Tansy")).toBeTruthy();
    expect(localStorage.getItem("delve.timeline.hideOut")).toBe("1");
  });
});

describe("Timeline faces (DEL-10)", () => {
  const faces = {
    chr_00000000000a: { portrait: { kind: "traits", describe: "a young elven wizard", seed: "mirela" } as const, hp: 3, hpMax: 12 },
    chr_00000000000b: { portrait: null, hp: 8, hpMax: 8 },
  };

  it("draws a character's portrait in place of its initial, which enlarges, with a bar of its hit points left", async () => {
    serve(fight());
    renderWith(<Timeline campaignId={CAMPAIGN} phone={false} faces={faces} />);
    const shown = await screen.findByTestId("timeline");
    const mirela = within(shown).getByTestId("timeline-slot-chr_00000000000a");
    const disc = mirela.querySelector("[data-face=portrait]")!;
    expect(disc.querySelector(".portrait.drawn svg")).not.toBeNull();
    expect(disc.textContent).not.toContain("M");
    expect(within(mirela).getByRole("button", { name: /Enlarge Mirela's portrait/ })).toBeTruthy();
    const bar = mirela.querySelector("[data-hp-left]")!;
    expect(bar.getAttribute("data-hp-left")).toBe("0.25");
    expect((bar.firstElementChild as HTMLElement).style.width).toBe("25%");

    const tansy = within(shown).getByTestId("timeline-slot-chr_00000000000b");
    expect(tansy.querySelector("[data-face]")).toBeNull();
    expect(tansy.textContent).toContain("T");
    expect(tansy.querySelector("[data-hp-left]")!.getAttribute("data-hp-left")).toBe("1");

    const goblin = within(shown).getByTestId("timeline-slot-mon_1");
    expect(goblin.querySelector("[data-face]")).toBeNull();
    expect(goblin.querySelector("[data-hp-left]")).toBeNull();
  });
});

describe("Timeline monsters (DEL-275)", () => {
  const goblin = { kind: "Goblin", picture: "goblin", version: "2026-10-28T15:00:00+00:00", painting: false };
  const rat = { kind: "Giant rat", picture: null, version: null, painting: false };

  function monsters() {
    return fight({
      slots: [
        slot("mon_1", "Goblin 1", 4, { side: "enemy", monster: goblin }),
        slot("mon_2", "Rat 1", 6, { side: "enemy", monster: rat }),
      ],
    });
  }

  it("shows a monster its kind's picture, which enlarges, and keeps the initial of one without", async () => {
    serve(monsters());
    renderWith(<Timeline campaignId={CAMPAIGN} phone={false} />);
    const shown = await screen.findByTestId("timeline");
    const one = within(shown).getByTestId("timeline-slot-mon_1");
    expect(one.querySelector("[data-face=monster] img")!.getAttribute("src")).toBe(
      "/api/monster-pictures/goblin?v=2026-10-28T15%3A00%3A00%2B00%3A00",
    );
    expect(within(one).getByRole("button", { name: "Enlarge the picture of Goblin 1" })).toBeTruthy();
    const two = within(shown).getByTestId("timeline-slot-mon_2");
    expect(two.querySelector("[data-face]")).toBeNull();
    expect(two.textContent).toContain("R");
    expect(within(two).queryByRole("button")).toBeNull();
  });

  it("offers an organiser Paint on a monster without a picture, for every table", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/timeline`]: () => json(200, { fight: monsters() }),
      "GET /api/monster-pictures?name=Giant%20rat": () =>
        json(200, { slug: "giant-rat", picture: false, version: null, painting: false, error: null, paid: true }),
      "POST /api/monster-pictures": () =>
        json(202, { slug: "giant-rat", picture: false, version: null, painting: true, error: null, paid: true }),
    });
    renderWith(<Timeline campaignId={CAMPAIGN} phone={false} canPaint />);
    const shown = await screen.findByTestId("timeline");
    expect(within(within(shown).getByTestId("timeline-slot-mon_1")).queryByRole("button", { name: /Paint/ })).toBeNull();
    fireEvent.click(within(shown).getByRole("button", { name: "Giant rat: no picture yet. Paint one" }));
    const dialog = await screen.findByTestId("paint-monster");
    expect(within(dialog).getByText("No picture of Giant rat yet")).toBeTruthy();
    expect(await within(dialog).findByText(/costs money/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: /Paint Giant rat/ }));
    await waitFor(() => expect(screen.queryByTestId("paint-monster")).toBeNull());
    const asked = fetchMock.mock.calls.find(([path, init]) => path === "/api/monster-pictures" && init?.method === "POST");
    expect(JSON.parse(String(asked![1]!.body))).toEqual({ name: "Giant rat", campaign_id: CAMPAIGN });
  });

  it("offers no Paint to a player", async () => {
    serve(monsters());
    renderWith(<Timeline campaignId={CAMPAIGN} phone={false} />);
    const shown = await screen.findByTestId("timeline");
    expect(within(shown).queryByRole("button", { name: /Paint/ })).toBeNull();
  });
});
