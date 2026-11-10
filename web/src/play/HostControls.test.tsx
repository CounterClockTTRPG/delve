import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { TableSession } from "./api";
import HostControls from "./HostControls";
import { CAMPAIGN, base, hostSeat, json, party, renderWith, seat, sent, stubFetch } from "./testing";

vi.mock("qrcode", () => ({ default: { toCanvas: vi.fn(async () => undefined) } }));

const ana = seat("seat_00000000000a", "Ana", { language: "nl", characters: ["chr_00000000000a"] });
const cy = seat("seat_00000000000c", "Cy", { role: "observer" });

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes() {
  return {
    [`GET ${base}/invite`]: () => json(200, { url: "http://192.168.1.20:7810/join/tok", join_token: "tok" }),
    [`GET ${base}/play/options`]: () => json(200, { tone: "classic", detail: 2, beat_timer_s: null, fallback: "hold_back" }),
    [`PUT ${base}/play/options`]: (init: RequestInit | undefined) =>
      json(200, { tone: "classic", detail: 2, beat_timer_s: null, fallback: "hold_back", ...JSON.parse(String(init?.body)) }),
    [`POST ${base}/go`]: () => json(202, { beat: { id: "beat_000000000001", status: "running" } }),
    [`PUT ${base}/seats/${ana.id}`]: () => json(200, { ...ana, role: "cohost" }),
    [`PUT ${base}/seats/${cy.id}`]: () => json(200, { ...cy, role: "player" }),
    [`POST ${base}/characters/chr_00000000000b/claim`]: () => json(200, {}),
    [`POST ${base}/characters/chr_00000000000a/release`]: () => json(200, {}),
  };
}

function renderControls(beatOpen = true, seats = [hostSeat, ana, cy], table?: TableSession) {
  return renderWith(
    <HostControls campaignId={CAMPAIGN} seats={seats} party={party} mySeat={hostSeat} beatOpen={beatOpen} table={table} />,
  );
}

const playing = (over: Partial<TableSession> = {}): TableSession => ({
  state: "playing",
  since: null,
  solo: false,
  absent: {},
  hands: [],
  away: [],
  ...over,
});

describe("HostControls", () => {
  it("removes a seat from the table after asking; the host's seat has no Remove (DEL-204)", async () => {
    const coHost = seat("seat_00000000000d", "Dee", { role: "cohost" });
    const fetchMock = stubFetch({
      ...routes(),
      [`POST ${base}/seats/${ana.id}/remove`]: () => json(200, { seat: ana }),
    });
    renderControls(false, [hostSeat, ana, cy, coHost]);
    const controls = await screen.findByTestId("host-controls");
    fireEvent.click(within(controls).getByText("Seats"));
    expect(within(controls).queryByTestId(`remove-${hostSeat.id}`)).toBeNull();
    expect(within(controls).getByTestId(`remove-${coHost.id}`), "the host removes a co-host too").toBeTruthy();
    fireEvent.click(within(controls).getByTestId(`remove-${ana.id}`));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog.textContent).toContain("Remove Ana from the table?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/seats/${ana.id}/remove`)).toEqual([{}]));
  });

  it("says go, and sets the beat timer and its fallback, without the organiser's options", async () => {
    const fetchMock = stubFetch(routes());
    renderControls();
    const controls = await screen.findByTestId("host-controls");

    fireEvent.click(within(controls).getByTestId("go"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/go`)).toEqual([{}]));

    const timer = (await within(controls).findByLabelText("Beat timer")) as HTMLSelectElement;
    await waitFor(() => expect(timer.value).toBe(""));
    fireEvent.change(timer, { target: { value: "180" } });
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ beat_timer_s: 180 }]));
    fireEvent.change(within(controls).getByLabelText("When the time runs out, characters whose player hasn't acted:"), {
      target: { value: "in_character" },
    });
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ beat_timer_s: 180 }, { fallback: "in_character" }]),
    );
  });

  it("the timer's choice names the characters it applies to", async () => {
    stubFetch(routes());
    renderControls();
    const controls = await screen.findByTestId("host-controls");
    const fallback = within(controls).getByLabelText(
      "When the time runs out, characters whose player hasn't acted:",
    ) as HTMLSelectElement;
    expect([...fallback.options].map((o) => o.textContent)).toEqual([
      "Do nothing (hold back)",
      "Are played cautiously by the DM",
    ]);
    expect(within(controls).getByText("The timer closes the beat for the host's characters too.")).toBeTruthy();
  });

  it("Go waits for an open beat", async () => {
    stubFetch(routes());
    renderControls(false);
    expect(((await screen.findByTestId("go")) as HTMLButtonElement).disabled).toBe(true);
  });

  it("gives roles, hands the host over after asking, and gives any character to any seat", async () => {
    const fetchMock = stubFetch(routes());
    renderControls();
    const row = (await screen.findByTestId(`seat-row-${ana.id}`)) as HTMLElement;

    fireEvent.click(within(row).getByRole("button", { name: "Make co-host" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/seats/${ana.id}`)).toEqual([{ role: "cohost" }]));

    const observer = screen.getByTestId(`seat-row-${cy.id}`);
    fireEvent.click(within(observer).getByRole("button", { name: "Make player" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/seats/${cy.id}`)).toEqual([{ role: "player" }]));

    // Handing the host over asks first; Cancel changes nothing.
    fireEvent.click(within(row).getByRole("button", { name: "Hand over the host" }));
    let dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(sent(fetchMock, "PUT", `${base}/seats/${ana.id}`)).toHaveLength(1);
    fireEvent.click(within(row).getByRole("button", { name: "Hand over the host" }));
    dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Hand over" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/seats/${ana.id}`)).toEqual([{ role: "cohost" }, { role: "host" }]));

    // Birch is free: give it to Ana. Ash is Ana's: give it to nobody. Observers aren't offered.
    const birch = screen.getByLabelText("Who plays Birch") as HTMLSelectElement;
    expect([...birch.options].map((o) => o.textContent)).toEqual(["Nobody", "Raf", "Ana"]);
    fireEvent.change(birch, { target: { value: ana.id } });
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/characters/chr_00000000000b/claim`)).toEqual([{ seat: ana.id }]),
    );
    const ash = screen.getByLabelText("Who plays Ash") as HTMLSelectElement;
    expect(ash.value).toBe(ana.id);
    fireEvent.change(ash, { target: { value: "" } });
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/characters/chr_00000000000a/release`)).toEqual([{}]));
  });

  it("folds the controls away; the invite is open while the host is alone, and folds once a second seat is present", async () => {
    stubFetch(routes());
    const { rerender } = renderControls(true, [hostSeat]);
    const controls = await screen.findByTestId("host-controls");
    const invite = within(controls).getByTestId("host-invite") as HTMLDetailsElement;
    const more = within(controls).getByTestId("host-table") as HTMLDetailsElement;
    expect(invite.tagName).toBe("DETAILS");
    expect(invite.open).toBe(true);
    expect(more.tagName).toBe("DETAILS");
    expect(more.open).toBe(false);
    // Go stays in reach, outside the fold.
    expect(more.contains(within(controls).getByTestId("go"))).toBe(false);

    const away = { ...ana, present: false };
    rerender(<HostControls campaignId={CAMPAIGN} seats={[hostSeat, away]} party={party} mySeat={hostSeat} beatOpen />);
    expect(invite.open, "a seat that is away leaves the host alone").toBe(true);
    rerender(<HostControls campaignId={CAMPAIGN} seats={[hostSeat, ana]} party={party} mySeat={hostSeat} beatOpen />);
    expect(invite.open).toBe(false);
  });

  it("lets the host turn paid images on", async () => {
    const fetchMock = stubFetch(routes());
    renderControls();
    const controls = await screen.findByTestId("host-controls");
    const paid = (await within(controls).findByLabelText("Paid images")) as HTMLInputElement;
    await waitFor(() => expect(paid.disabled).toBe(false));
    expect(paid.checked).toBe(false);
    expect(within(controls).queryByRole("button", { name: "Paint this scene" })).toBeNull();

    fireEvent.click(paid);
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ paid_images: true }]));
    // Paint this scene is the composer's now, for every seat that acts.
    expect(within(controls).queryByRole("button", { name: "Paint this scene" })).toBeNull();
  });

  it("lets the host say how many paid pictures a day, once paid images are on (DEL-153)", async () => {
    const options = { tone: "classic", detail: 2, beat_timer_s: null, fallback: "hold_back" };
    const fetchMock = stubFetch({
      ...routes(),
      [`GET ${base}/play/options`]: () => json(200, { ...options, paid_images: true, paid_images_per_day: 20 }),
    });
    renderControls();
    const controls = await screen.findByTestId("host-controls");
    const perDay = (await within(controls).findByLabelText("Paid pictures a day")) as HTMLSelectElement;
    await waitFor(() => expect(perDay.value).toBe("20"));
    fireEvent.change(perDay, { target: { value: "40" } });
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ paid_images_per_day: 40 }]));
  });

  it("shows no limit while paid images are off", async () => {
    stubFetch(routes());
    renderControls();
    const controls = await screen.findByTestId("host-controls");
    await within(controls).findByLabelText("Paid images");
    expect(within(controls).queryByLabelText("Paid pictures a day")).toBeNull();
  });

  it("leaves the paid images switch to the host: a co-host doesn't get it", async () => {
    stubFetch(routes());
    renderWith(
      <HostControls campaignId={CAMPAIGN} seats={[hostSeat, ana]} party={party} mySeat={{ id: ana.id, role: "cohost" }} beatOpen />,
    );
    await screen.findByTestId("host-controls");
    expect(screen.queryByLabelText("Paid images")).toBeNull();
  });

  it("marks a seat away and back, and sets a character's part, while the session is under way (DEL-224)", async () => {
    const garrek = party[0];
    const fetchMock = stubFetch({
      ...routes(),
      [`POST ${base}/away`]: () => json(200, { table: playing() }),
      [`DELETE ${base}/away/${ana.id}`]: () => json(200, { table: playing() }),
      [`PUT ${base}/parts/${garrek.id}`]: () => json(200, { table: playing() }),
    });
    const { unmount } = renderControls(false, [hostSeat, ana, cy], playing());
    const row = (await screen.findByTestId(`seat-row-${ana.id}`)) as HTMLElement;
    expect(screen.queryByTestId(`mark-away-${cy.id}`), "an observer isn't waited for").toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Mark away" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/away`)).toEqual([{ part: null, seat_id: ana.id }]));

    const parts = screen.getByTestId("host-parts");
    const select = within(parts).getByLabelText(`${garrek.name}'s part while their player doesn't act`) as HTMLSelectElement;
    expect(select.value).toBe("");
    fireEvent.change(select, { target: { value: "out" } });
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/parts/${garrek.id}`)).toEqual([{ part: "out" }]));
    unmount();

    renderControls(false, [hostSeat, ana, cy], playing({ away: [{ seat_id: ana.id, at: "", part: null }], absent: { [garrek.id]: "out" } }));
    const back = (await screen.findByTestId(`seat-row-${ana.id}`)) as HTMLElement;
    expect((screen.getByLabelText(`${garrek.name}'s part while their player doesn't act`) as HTMLSelectElement).value).toBe("out");
    fireEvent.click(within(back).getByRole("button", { name: "Back" }));
    const deleted = () =>
      fetchMock.mock.calls.filter(([url, init]) => String(url) === `${base}/away/${ana.id}` && init?.method === "DELETE");
    await waitFor(() => expect(deleted()).toHaveLength(1));
  });

  it("has no away or parts while the table gathers", async () => {
    stubFetch(routes());
    renderControls(false, [hostSeat, ana, cy], playing({ state: "gathering" }));
    await screen.findByTestId(`seat-row-${ana.id}`);
    expect(screen.queryByTestId(`mark-away-${ana.id}`)).toBeNull();
    expect(screen.queryByTestId("host-parts")).toBeNull();
  });

  it("sets up the hotseat: switched on, a player added, a character ticked (DEL-365)", async () => {
    let stored: Record<string, unknown> = { tone: "classic", detail: 2, beat_timer_s: null, fallback: "hold_back", hotseat: false, hotseat_players: [] };
    const fetchMock = stubFetch({
      ...routes(),
      [`GET ${base}/play/options`]: () => json(200, stored),
      [`PUT ${base}/play/options`]: (init: RequestInit | undefined) => {
        const body = JSON.parse(String(init?.body));
        if (body.hotseat_players) {
          body.hotseat_players = body.hotseat_players.map((p: { id?: string }, i: number) => ({ id: p.id ?? `hs_${i}`, ...p }));
        }
        stored = { ...stored, ...body };
        return json(200, stored);
      },
    });
    renderControls(false, [hostSeat, ana, cy]);
    const controls = await screen.findByTestId("host-controls");
    fireEvent.click(within(controls).getByText("Seats"));
    const setup = within(controls).getByTestId("hotseat-setup");
    await waitFor(() => expect(within(setup).getByTestId("hotseat-on")).not.toHaveProperty("disabled", true));
    fireEvent.click(within(setup).getByTestId("hotseat-on"));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/play/options`)).toEqual([{ hotseat: true }]));
    fireEvent.change(await within(setup).findByTestId("hotseat-name"), { target: { value: "Anna" } });
    fireEvent.click(within(setup).getByRole("button", { name: "Add a player" }));
    await waitFor(() => expect(within(setup).getAllByTestId("hotseat-player")).toHaveLength(1));
    const player = within(setup).getByTestId("hotseat-player");
    // Ash is Ana's, who plays at her own screen: only Birch and Cedar can be given out.
    expect(within(player).queryByLabelText("Ash")).toBeNull();
    fireEvent.click(within(player).getByLabelText("Birch"));
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", `${base}/play/options`).at(-1)).toEqual({
        hotseat_players: [{ id: "hs_0", name: "Anna", characters: ["chr_00000000000b"] }],
      }),
    );
    expect(within(setup).getByText("Only characters this screen plays can be given out: nobody else at the table plays them.")).toBeTruthy();
  });
});
