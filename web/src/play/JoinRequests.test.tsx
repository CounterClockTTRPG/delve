import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import JoinRequests from "./JoinRequests";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "./testing";

afterEach(() => vi.unstubAllGlobals());

const waiting = {
  id: "jrq_00000000000a",
  campaign_id: CAMPAIGN,
  status: "pending",
  messages: [{ from: "player", name: "Ana", text: "Can I join?", at: "2026-10-27T10:00:00+00:00" }],
  created_at: "2026-10-27T10:00:00+00:00",
  decided_at: null,
  seat_id: null,
  account: { id: "acc_00000000000a", display_name: "Ana", profile: null },
};

describe("JoinRequests (DEL-204)", () => {
  it("shows each waiting request, replies, accepts, and declines with a reason", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/requests`]: () => json(200, [waiting, { ...waiting, id: "jrq_00000000000b", status: "declined" }]),
      "POST /api/requests/jrq_00000000000a/messages": () => json(201, { request: waiting }),
      [`POST ${base}/requests/jrq_00000000000a/accept`]: () => json(200, { request: { ...waiting, status: "accepted" } }),
      [`POST ${base}/requests/jrq_00000000000a/decline`]: () => json(200, { request: { ...waiting, status: "declined" } }),
    });
    renderWith(<JoinRequests campaignId={CAMPAIGN} full={false} />);
    const box = await screen.findByTestId("join-requests");
    expect(within(box).getByText("Requests to join (1)")).toBeTruthy();
    expect(box.textContent).toContain("Can I join?");
    fireEvent.change(within(box).getByLabelText("Your reply"), { target: { value: "Welcome!" } });
    fireEvent.click(within(box).getByRole("button", { name: "Send" }));
    await waitFor(() => expect(sent(fetchMock, "POST", "/api/requests/jrq_00000000000a/messages")).toEqual([{ text: "Welcome!" }]));
    fireEvent.click(within(box).getByTestId("accept-jrq_00000000000a"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/requests/jrq_00000000000a/accept`)).toEqual([{}]));
    fireEvent.click(within(box).getByTestId("decline-jrq_00000000000a"));
    fireEvent.change(within(box).getByLabelText("Why, for them (optional)"), { target: { value: " Full for now. " } });
    fireEvent.click(within(box).getByTestId("decline-confirm-jrq_00000000000a"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/requests/jrq_00000000000a/decline`)).toEqual([{ reason: "Full for now." }]),
    );
  });

  it("says who wants to watch, and lets a watcher in at a full table (DEL-215)", async () => {
    stubFetch({ [`GET ${base}/requests`]: () => json(200, [{ ...waiting, role: "observer" }]) });
    renderWith(<JoinRequests campaignId={CAMPAIGN} full />);
    const box = await screen.findByTestId("join-requests");
    expect(within(box).getByTestId("wants-to-watch-jrq_00000000000a").textContent).toBe("wants to watch");
    expect((within(box).getByTestId("accept-jrq_00000000000a") as HTMLButtonElement).disabled, "a watcher takes no place").toBe(false);
  });

  it("takes no Accept at a full table, and shows nothing while none waits", async () => {
    stubFetch({ [`GET ${base}/requests`]: () => json(200, [waiting]) });
    const { unmount } = renderWith(<JoinRequests campaignId={CAMPAIGN} full />);
    const box = await screen.findByTestId("join-requests");
    expect((within(box).getByTestId("accept-jrq_00000000000a") as HTMLButtonElement).disabled).toBe(true);
    expect(box.textContent).toContain("The table is full");
    unmount();
    stubFetch({ [`GET ${base}/requests`]: () => json(200, []) });
    renderWith(<JoinRequests campaignId={CAMPAIGN} full={false} />);
    await waitFor(() => expect(screen.queryByTestId("join-requests")).toBeNull());
  });
});
