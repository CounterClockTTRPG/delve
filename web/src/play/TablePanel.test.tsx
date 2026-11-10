import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProfileCards } from "../profile/ProfileCard";
import type { Seat } from "./api";
import { boardZone } from "../board/testing";
import TablePanel from "./TablePanel";
import { CAMPAIGN, base, hostSeat, json, renderWith, seat, sent, stubFetch } from "./testing";

vi.mock("qrcode", () => ({ default: { toCanvas: vi.fn(async () => undefined) } }));

const ana = seat("seat_00000000000a", "Ana", { language: "nl", characters: ["chr_00000000000a"] });
const coHost = seat("seat_00000000000b", "Bo", { role: "cohost" });

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderPanel(mine: Seat, onLeft = vi.fn(), more: Parameters<typeof stubFetch>[0] = {}, campaignName = "The Sunless Citadel") {
  const fetchMock = stubFetch({
    "GET /api/board": () => json(200, { zones: [], may_create: false, signed_in: true }),
    [`GET ${base}/invite`]: () => json(200, { url: "http://192.168.1.20:7810/join/tok", join_token: "tok" }),
    [`GET ${base}/play/options`]: () => json(200, { tone: "classic", detail: 2, beat_timer_s: null, fallback: "hold_back" }),
    [`POST ${base}/leave`]: () => new Response(null, { status: 204 }),
    ...more,
  });
  renderWith(
    <TablePanel
      campaignId={CAMPAIGN}
      campaignName={campaignName}
      seats={[hostSeat, ana, coHost]}
      mySeat={mine}
      onLeft={onLeft}
    />,
  );
  return { onLeft, fetchMock };
}

describe("TablePanel", () => {
  it("shows who is at the table; the talk, the questions and the host's controls are elsewhere", async () => {
    renderPanel(hostSeat);
    const panel = screen.getByTestId("table-panel");
    const seats = within(panel).getByTestId("table-seats");
    expect(seats.textContent).toContain("Ana");
    expect(seats.textContent).toContain("Co-host");
    expect(within(panel).queryByTestId("talk-panel"), "the talk has a place of its own (DEL-199)").toBeNull();
    expect(within(panel).queryByTestId("ask-panel"), "questions to the DM are in the story").toBeNull();
    expect(within(panel).queryByTestId("host-controls")).toBeNull();
    expect(within(panel).queryByRole("button", { name: "Leave the table" }), "the host hands over first").toBeNull();
  });

  it("links to the table's zone on the board", async () => {
    renderPanel(ana, vi.fn(), {
      "GET /api/board": () => json(200, { zones: [boardZone({ id: "zon_00000000000b", campaign_id: CAMPAIGN })], may_create: false, signed_in: true }),
    });
    const link = await screen.findByRole("link", { name: "Board" });
    expect(link.getAttribute("href")).toBe("/board/zon_00000000000b");
    expect(screen.queryByRole("button", { name: "Make the table's zone" })).toBeNull();
  });

  it("lets the host make the table's zone, named for the campaign, when there is none", async () => {
    const made = boardZone({ id: "zon_00000000000c", campaign_id: CAMPAIGN });
    let zones: unknown[] = [];
    const { fetchMock } = renderPanel(hostSeat, vi.fn(), {
      "GET /api/board": () => json(200, { zones, may_create: false, signed_in: true }),
      "POST /api/board/zones": () => {
        zones = [made];
        return json(201, { zone: made });
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: "Make the table's zone" }));
    expect((await screen.findByRole("link", { name: "Board" })).getAttribute("href")).toBe("/board/zon_00000000000c");
    expect(sent(fetchMock, "POST", "/api/board/zones")).toEqual([
      { name: "The Sunless Citadel", read: "table", write: "table", campaign_id: CAMPAIGN },
    ]);
  });

  it("names the table's zone within 80 characters, and something before the campaign's name is known", async () => {
    for (const [campaignName, name] of [
      [`  ${"A long name ".repeat(10)}`, "A long name ".repeat(7).slice(0, 80).trim()],
      ["", "Table"],
    ]) {
      const { fetchMock } = renderPanel(hostSeat, vi.fn(), { "POST /api/board/zones": () => json(201, { zone: boardZone() }) }, campaignName);
      fireEvent.click(await screen.findByRole("button", { name: "Make the table's zone" }));
      await waitFor(() => expect(sent(fetchMock, "POST", "/api/board/zones")).toEqual([{ name, read: "table", write: "table", campaign_id: CAMPAIGN }]));
      cleanup();
    }
  });

  it("shows why the table's zone was not made, in the server's words", async () => {
    renderPanel(hostSeat, vi.fn(), { "POST /api/board/zones": () => json(409, { error: "That campaign has its zone already." }) });
    fireEvent.click(await screen.findByRole("button", { name: "Make the table's zone" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That campaign has its zone already.");
  });

  it("offers a player who is not the host no way to make the zone", async () => {
    renderPanel(ana);
    await screen.findByText("Leave the table");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Make the table's zone" })).toBeNull());
  });

  it("lets a co-host leave the table", () => {
    renderPanel(coHost);
    expect(screen.getByRole("button", { name: "Leave the table" })).toBeTruthy();
  });

  it("shows a player no host controls, and lets them leave", async () => {
    const { onLeft } = renderPanel(ana);
    expect(screen.queryByTestId("host-controls")).toBeNull();
    expect(screen.queryByTestId("invite-panel")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Leave the table" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Leave" }));
    await waitFor(() => expect(onLeft).toHaveBeenCalled());
    expect(sent(vi.mocked(fetch), "POST", `${base}/leave`)).toEqual([{}]);
  });

  it("shows each seat's avatar beside its name, and opens its card", async () => {
    const profile = { account_id: "acc_00000000000a", display_name: "Ana", pronouns: "she/her", avatar: { emblem: "oak" }, colour: "jade" };
    stubFetch({ "GET /api/profiles/acc_00000000000a": () => json(200, { ...profile, about: "Bard." }) });
    renderWith(
      <ProfileCards>
        <TablePanel campaignId={CAMPAIGN} campaignName="The Sunless Citadel" seats={[hostSeat, { ...ana, profile }]} mySeat={hostSeat} onLeft={vi.fn()} />
      </ProfileCards>,
    );
    const seats = screen.getByTestId("table-seats");
    expect(seats.querySelector(".avatar[data-emblem='oak']")).not.toBeNull();
    fireEvent.click(within(seats).getByRole("button", { name: "Ana" }));
    expect(await screen.findByRole("dialog", { name: "Ana" })).toBeTruthy();
  });
});
