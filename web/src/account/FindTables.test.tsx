import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, json, renderWith, sent, stubFetch } from "../play/testing";
import FindTables from "./FindTables";
import MyRequests from "./MyRequests";
import type { JoinRequest, PublicTable } from "./api";

afterEach(() => vi.unstubAllGlobals());

const table = (over: Partial<PublicTable> = {}): PublicTable => ({
  campaign_id: CAMPAIGN,
  name: "Puppets",
  module_title: "The Puppet Show",
  ruleset: "adnd2e",
  setting: "greyhawk",
  ruleset_title: "AD&D 2nd Edition",
  setting_title: "Greyhawk",
  description: "Newcomers **welcome**.",
  slots: 4,
  taken: 2,
  full: false,
  house_rules: [],
  host: { display_name: "Raf", profile: null },
  seated: false,
  request: null,
  ...over,
});

const request = (over: Partial<JoinRequest> = {}): JoinRequest => ({
  id: "jrq_00000000000a",
  campaign_id: CAMPAIGN,
  status: "pending",
  messages: [{ from: "player", name: "Ana", text: "I play Saturdays.", at: "2026-10-27T10:00:00+00:00" }],
  created_at: "2026-10-27T10:00:00+00:00",
  decided_at: null,
  seat_id: null,
  account: { id: "acc_00000000000a", display_name: "Ana", profile: null },
  campaign: { id: CAMPAIGN, name: "Puppets", module_title: "The Puppet Show" },
  ...over,
});

describe("Find a table (DEL-204)", () => {
  it("lists a public table with its host, places and description, and asks to join with a note", async () => {
    const fetchMock = stubFetch({
      "GET /api/tables": () => json(200, [table()]),
      [`POST /api/tables/${CAMPAIGN}/requests`]: () => json(201, { request: request() }),
      "GET /api/account/requests": () => json(200, []),
    });
    renderWith(<FindTables />, "/play");
    const card = await screen.findByTestId(`find-table-${CAMPAIGN}`);
    expect(card.textContent).toContain("Hosted by Raf");
    expect(card.textContent).toContain("AD&D 2nd Edition, Greyhawk");
    expect(within(card).getByTestId("table-places").textContent).toBe("2 of 4 places taken");
    expect(card.querySelector(".table-description strong")?.textContent).toBe("welcome");
    fireEvent.click(within(card).getByTestId("find-ask"));
    fireEvent.change(within(card).getByLabelText("A note to the host"), { target: { value: " I play Saturdays. " } });
    fireEvent.click(within(card).getByTestId("find-send"));
    await waitFor(() => expect(sent(fetchMock, "POST", `/api/tables/${CAMPAIGN}/requests`)).toEqual([{ note: "I play Saturdays.", role: "player" }]));
  });

  it("says a request waits, opens a table the account sits at, and takes no request at a full table", async () => {
    stubFetch({
      "GET /api/tables": () =>
        json(200, [
          table({ request: { id: "jrq_00000000000a", status: "pending" } }),
          table({ campaign_id: "cmp_00000000000b", seated: true }),
          table({ campaign_id: "cmp_00000000000c", full: true, taken: 4 }),
        ]),
    });
    renderWith(<FindTables />, "/play");
    expect((await screen.findByTestId("find-waiting")).textContent).toContain("hasn't answered yet");
    expect(within(screen.getByTestId("find-table-cmp_00000000000b")).getByRole("link", { name: "Open the table" })).toBeTruthy();
    const full = screen.getByTestId("find-table-cmp_00000000000c");
    expect(within(full).queryByTestId("find-ask")).toBeNull();
    expect(full.textContent).toContain("The table is full.");
  });
});

describe("Your requests (DEL-204)", () => {
  it("shows each request's thread, answers the host, and withdraws while it waits", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/requests": () =>
        json(200, [
          request({
            messages: [
              ...request().messages,
              { from: "host", name: "Raf", text: "Welcome! Any experience?", at: "2026-10-27T10:05:00+00:00" },
            ],
          }),
        ]),
      "POST /api/requests/jrq_00000000000a/messages": () => json(201, { request: request() }),
      "POST /api/requests/jrq_00000000000a/withdraw": () => json(200, { request: request({ status: "withdrawn" }) }),
    });
    renderWith(<MyRequests />, "/play");
    const mine = await screen.findByTestId("my-requests");
    expect(mine.textContent).toContain("Waiting for the host");
    expect(mine.textContent).toContain("Welcome! Any experience?");
    fireEvent.change(within(mine).getByLabelText("Your reply"), { target: { value: "Some, in 2e." } });
    fireEvent.click(within(mine).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/requests/jrq_00000000000a/messages")).toEqual([{ text: "Some, in 2e." }]));
    fireEvent.click(within(mine).getByRole("button", { name: "Withdraw" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/requests/jrq_00000000000a/withdraw")).toEqual([{}]));
  });

  it("opens the table of an accepted request, and shows nothing without requests", async () => {
    stubFetch({ "GET /api/account/requests": () => json(200, [request({ status: "accepted", seat_id: "seat_00000000000a" })]) });
    const { unmount } = renderWith(<MyRequests />, "/play");
    const mine = await screen.findByTestId("my-requests");
    expect(within(mine).getByRole("link", { name: "Play" })).toBeTruthy();
    expect(within(mine).queryByLabelText("Your reply"), "a decided request takes no reply").toBeNull();
    unmount();
    stubFetch({ "GET /api/account/requests": () => json(200, []) });
    renderWith(<MyRequests />, "/play");
    await waitFor(() => expect(screen.queryByTestId("my-requests")).toBeNull());
  });
});

describe("asking to watch (DEL-215)", () => {
  it("asks to watch, a full table too, and offers no watching where the table takes none", async () => {
    const fetchMock = stubFetch({
      "GET /api/tables": () => json(200, [table({ full: true, taken: 4, slots: 4 }), table({ campaign_id: "cmp_00000000000z", name: "Closed", observers: "nobody" })]),
      [`POST /api/tables/${CAMPAIGN}/requests`]: () => json(201, { request: request({ role: "observer" }) }),
      "GET /api/account/requests": () => json(200, []),
    });
    renderWith(<FindTables />, "/play");
    const full = await screen.findByTestId(`find-table-${CAMPAIGN}`);
    const closed = screen.getByTestId("find-table-cmp_00000000000z");
    expect(within(full).queryByTestId("find-ask"), "a full table takes no player").toBeNull();
    fireEvent.click(within(full).getByTestId("find-ask-watch"));
    fireEvent.click(within(full).getByTestId("find-send"));
    await waitFor(() => expect(sent(fetchMock, "POST", `/api/tables/${CAMPAIGN}/requests`)).toEqual([{ note: "", role: "observer" }]));
    expect(within(closed).queryByTestId("find-ask-watch")).toBeNull();
  });
});
