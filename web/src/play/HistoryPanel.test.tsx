import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Play from "../routes/Play";
import HistoryPanel from "./HistoryPanel";
import { CAMPAIGN, FakeEventSource, base, hostSeat, json, me, playRoutes, renderWith, seat, stubFetch } from "./testing";

beforeEach(() => {
  FakeEventSource.open = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const TABLE_MD = "## The party\n\nAsh and **Birch** came out of the crypt.";

describe("HistoryPanel", () => {
  it("shows the table's history as Markdown", async () => {
    stubFetch({ [`GET ${base}/history`]: () => json(200, { status: "done", table_md: TABLE_MD }) });
    renderWith(<HistoryPanel campaignId={CAMPAIGN} />);
    expect((await screen.findByRole("heading", { name: "The party" })).tagName).toBe("H4");
    expect(screen.getByText("Birch").tagName).toBe("STRONG");
  });

  it("says when the history is still being written", async () => {
    stubFetch({ [`GET ${base}/history`]: () => json(200, { status: "writing", table_md: "" }) });
    renderWith(<HistoryPanel campaignId={CAMPAIGN} />);
    expect(await screen.findByText("The history is being written.")).toBeTruthy();
  });
});

describe("The play screen's History tab", () => {
  const player = seat("seat_00000000000p", "Ori");

  it("is there for a seat when the campaign has a history, and opens it", async () => {
    stubFetch({
      ...playRoutes(undefined, [], { me: me(player), seats: [hostSeat, player] }),
      [`GET ${base}/history`]: () => json(200, { status: "done", table_md: TABLE_MD }),
    });
    renderWith(<Play />);
    fireEvent.click(await screen.findByRole("tab", { name: "Maps" }));
    fireEvent.click(await screen.findByRole("tab", { name: "History" }));
    expect(await screen.findByRole("heading", { name: "The party" })).toBeTruthy();
  });

  it("is absent when the campaign has none", async () => {
    const fetchMock = stubFetch(playRoutes(undefined, [], { me: me(player), seats: [hostSeat, player] }));
    renderWith(<Play />);
    fireEvent.click(await screen.findByRole("tab", { name: "Maps" }));
    expect(await screen.findByRole("tab", { name: "Setting" })).toBeTruthy();
    await waitFor(() => expect(fetchMock.mock.calls.map(([p]) => String(p))).toContain(`${base}/history`));
    await waitFor(() => expect(screen.queryByRole("tab", { name: "History" })).toBeNull());
  });

  it("reads the history again on a history event, never on a timer, until it is written (DEL-172)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let status = "writing";
      const fetchMock = stubFetch({
        ...playRoutes(undefined, [], { me: me(player), seats: [hostSeat, player] }),
        [`GET ${base}/history`]: () => json(200, { status, table_md: status === "done" ? TABLE_MD : "" }),
      });
      const reads = () => fetchMock.mock.calls.filter(([p]) => p === `${base}/history`).length;
      renderWith(<Play />);
      fireEvent.click(await screen.findByRole("tab", { name: "Maps" }));
      fireEvent.click(await screen.findByRole("tab", { name: "History" }));
      expect(await screen.findByText("The history is being written.")).toBeTruthy();
      const before = reads();
      await vi.advanceTimersByTimeAsync(20_000);
      expect(reads()).toBe(before);

      status = "done";
      FakeEventSource.emit("history", { campaign_id: "cmp_other0000000" });
      FakeEventSource.emit("history", { campaign_id: CAMPAIGN });
      expect(await screen.findByRole("heading", { name: "The party" })).toBeTruthy();
      expect(reads()).toBe(before + 1);
    } finally {
      vi.useRealTimers();
    }
  });
});
