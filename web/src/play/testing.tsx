// Test helpers for the play screen: a routed fetch, a fake event stream and a renderer.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import type { Character } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { seatView } from "../worldmap/testing";
import type { Me } from "../account/api";
import type { PartyMember, PlayState, Seat, StoryEntry, World } from "./api";

export const CAMPAIGN = "cmp_00000000000a";
export const base = `/api/campaigns/${CAMPAIGN}`;

export type Handler = (init: RequestInit | undefined) => Response;

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** Stubs fetch with `routes`, keyed "METHOD path"; anything else is a 404. */
export function stubFetch(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function sent(fetchMock: ReturnType<typeof vi.fn>, method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([p, init]) => p === path && init?.method === method)
    .map(([, init]) => JSON.parse(String(init.body)));
}

/** EventSource, as far as subscribeEvents uses it; `emit` delivers an event to every open stream. */
export class FakeEventSource {
  static open: FakeEventSource[] = [];
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};

  constructor(public url: string) {
    FakeEventSource.open.push(this);
  }

  addEventListener(type: string, listener: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(listener);
  }

  close() {
    FakeEventSource.open = FakeEventSource.open.filter((s) => s !== this);
  }

  static emit(type: string, data: unknown) {
    act(() => {
      for (const source of FakeEventSource.open)
        for (const listener of source.listeners[type] ?? [])
          listener(new MessageEvent(type, { data: JSON.stringify(data) }));
    });
  }
}

export function entry(seq: number, kind: StoryEntry["kind"], payload: StoryEntry["payload"], beat = "beat_000000000001") {
  return { id: `ste_${String(seq).padStart(12, "0")}`, campaign_id: CAMPAIGN, beat_id: beat, seq, kind, payload, at: "2026-10-17T20:00:00Z" };
}

export function member(id: string, name: string, hp = 8, hpMax = 10): PartyMember {
  return { id, name, hp, hp_max: hpMax, ac: 5, conditions: [] };
}

export const party = [
  member("chr_00000000000a", "Ash"),
  member("chr_00000000000b", "Birch", 3, 9),
  member("chr_00000000000c", "Cedar"),
];

export function playState(overrides: Partial<PlayState> = {}): PlayState {
  return {
    beat: null,
    party,
    positions: [{ map: "crypt", location: "room.entry", label: "Entry", characters: ["Ash", "Birch", "Cedar"] }],
    combat: null,
    session_number: 1,
    time_of_day: "morning",
    table: { state: "playing", since: null, solo: false, absent: {}, hands: [], away: [] },
    ...overrides,
  };
}

export function character(id: string, name: string): Character {
  return {
    id,
    campaign_id: CAMPAIGN,
    name,
    kind: "pc",
    order: 0,
    encumbrance: null,
    created_at: "2026-10-17T12:00:00Z",
    sheet: {
      kind: "pc",
      label: name,
      race: "Human",
      gender: "",
      cls: "Fighter",
      levels: { fighter: 1 },
      hp_max: 10,
      ac: 5,
      thac0: 20,
      saves: {},
      ability_scores: {},
      attacks: [],
      weapon: "",
      movement_rate: 12,
      alignment: "",
      spell_slots: {},
    },
    state: { hp: 8, xp: 0, conditions: [], effects: [] },
  };
}

export const HOST_SEAT = "seat_00000000000h";

/** A seat at the table; the host's plays nothing of its own (the free PCs are the host's to act for). */
export function seat(id: string, name: string, overrides: Partial<Seat> = {}): Seat {
  return { id, name, language: "en", role: "player", organiser: false, present: true, characters: [], profile: null, ...overrides };
}

export const hostSeat = seat(HOST_SEAT, "Raf", { role: "host", organiser: true });

/** `/api/me` for a seat of the campaign: the owner's host seat unless told otherwise. */
export function me(of: Seat = hostSeat): Me {
  const owner = of.id === HOST_SEAT;
  return {
    principal: { id: owner ? "owner" : `seat:${of.id}`, roles: of.organiser ? ["organiser"] : [] },
    seat: {
      id: of.id,
      campaign_id: CAMPAIGN,
      campaign_name: "The Crypt",
      name: of.name,
      language: of.language,
      role: of.role,
      organiser: of.organiser,
    },
  };
}

/** The routes a play screen asks for when it opens, with an empty story and no running beat: the owner alone, as
 * the host. */
export function playRoutes(
  state: PlayState = playState(),
  story: StoryEntry[] = [],
  table: { me?: Me; seats?: Seat[] } = {},
): Record<string, Handler> {
  return {
    [`GET /api/me?campaign=${CAMPAIGN}`]: () => json(200, table.me ?? me()),
    [`GET ${base}/seats`]: () => json(200, table.seats ?? [hostSeat]),
    [`GET ${base}/story?limit=50`]: () => json(200, { entries: story, has_more: false }),
    [`GET ${base}/play/state`]: () => json(200, state),
    [`GET ${base}/play/options`]: () => json(200, { tone: "classic", detail: 2 }),
    [`GET ${base}/characters`]: () => json(200, [character("chr_00000000000a", "Ash")]),
    [`GET ${base}/maps/crypt/view?characters=chr_00000000000a,chr_00000000000b,chr_00000000000c`]: () =>
      json(200, { svg: '<svg data-view="characters"></svg>' }),
  };
}

export function renderWith(ui: ReactNode, path = `/play/${CAMPAIGN}`) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrap = (shown: ReactNode) => (
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/play/:campaignId" element={shown} />
              <Route path="/play" element={shown} />
            </Routes>
          </MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
  const rendered = render(wrap(ui));
  // Rendering again keeps the providers and their state, such as the query cache.
  return { ...rendered, client, rerender: (next: ReactNode) => rendered.rerender(wrap(next)) };
}

/** What the characters know of the world (plan 6), as `GET …/world` answers it. */
export const world: World = {
  date: "4 Planting 576 CY",
  weather: { label: "light rain", effect: "" },
  position: { map: "greyhawk-region", at_label: "Greyhawk" },
  quests: [
    {
      id: "relic",
      title: "Find the relic",
      giver: "the abbot",
      scope: "local",
      stakes: "The ward fails.",
      status: "active",
      started_day: 1,
      ended_day: null,
      log: [{ day: 1, text: "The abbot sent us." }],
    },
  ],
  factions: [{ id: "watch", name: "The Watch", standing: "Friendly" }],
  possessions: [
    {
      id: "pos_00000000000a",
      name: "Bess",
      kind: "mount",
      owner: "Ash",
      owner_id: "chr_00000000000a",
      location: "",
      value_gp: 75,
      description: "A grey mare.",
      inventory: [],
      stats: { mv: 24 },
      portrait: null,
    },
  ],
};

export const worldRoutes = (maps = [{ name: "greyhawk-region", title: "Greyhawk region" }]) => ({
  [`GET ${base}/world`]: () => json(200, world),
  [`GET ${base}/world-maps`]: () => json(200, maps),
  [`GET ${base}/world-maps/greyhawk-region/view`]: () => json(200, seatView()),
});
