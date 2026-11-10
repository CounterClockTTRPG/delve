import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Campaign, Schedule } from "../api";
import TableSchedule from "../campaign/TableSchedule";
import { I18nProvider } from "../i18n";
import NextSessionLine, { scheduleRule, sessionWhen } from "./NextSession";
import NextSessionControls from "./NextSessionControls";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "./testing";

afterEach(() => vi.unstubAllGlobals());

const schedule: Schedule = { every_weeks: 2, first: "2026-11-07", start: "20:00", end: "22:00", time_zone: "Europe/Brussels", changes: [] };
// Saturday 7 November 2026, 20:00–22:00 in Brussels (winter time, UTC+1).
const session = { on: "2026-11-07", starts_at: "2026-11-07T19:00:00+00:00", ends_at: "2026-11-07T21:00:00+00:00", moved: false };

describe("a schedule's words (DEL-204 part C)", () => {
  it("shows a session in the viewer's own time zone", () => {
    expect(sessionWhen(session, "en-GB", "Europe/Brussels")).toBe("Sat 7 Nov, 20:00–22:00");
    expect(sessionWhen(session, "en-GB", "America/New_York")).toBe("Sat 7 Nov, 14:00–16:00");
  });

  it("says the rule in the host's words", () => {
    const t = (key: string, vars?: Record<string, string>) => `${key}:${JSON.stringify(vars)}`;
    expect(scheduleRule(t, schedule, "en")).toContain('"weekday":"Saturday"');
    expect(scheduleRule(t, schedule, "en")).toContain("schedule.ruleEvery");
    expect(scheduleRule(t, { ...schedule, every_weeks: 1 }, "en")).toContain("schedule.ruleWeekly");
  });

  it("marks a moved session, and shows nothing without a schedule", () => {
    const { rerender } = render(
      <I18nProvider language="en">
        <NextSessionLine sessions={[{ ...session, moved: true }]} schedule={schedule} />
      </I18nProvider>,
    );
    expect(screen.getByTestId("next-session").textContent).toContain("Next session:");
    expect(screen.getByTestId("next-session").textContent).toContain("(moved)");
    expect(screen.getByTestId("next-session").textContent).toContain("Every 2 weeks on Saturday, 20:00–22:00, Europe/Brussels time");
    rerender(
      <I18nProvider language="en">
        <NextSessionLine sessions={[]} schedule={null} />
      </I18nProvider>,
    );
    expect(screen.queryByTestId("next-session")).toBeNull();
  });
});

describe("TableSchedule", () => {
  const campaign: Campaign = {
    id: CAMPAIGN, name: "Tuesday", module_id: "mod_00000000000a", revision: 1, created_at: "2026-10-17T12:00:00Z",
    ruleset: "adnd2e", setting: null, status: "in_progress", schedule: null, next_sessions: [],
  };

  it("saves the rule, and clears it", async () => {
    const fetchMock = stubFetch({
      "GET /api/time-zones": () => json(200, ["Asia/Kolkata", "Europe/Brussels", "Europe/Riga", "UTC"]),
      [`PUT ${base}/schedule`]: () => json(200, { ...campaign, schedule }),
    });
    const { rerender } = renderWith(<TableSchedule campaign={campaign} />);
    const form = screen.getByTestId("table-schedule");
    fireEvent.change(within(form).getByLabelText("How often"), { target: { value: "2" } });
    fireEvent.change(within(form).getByLabelText("First session"), { target: { value: "2026-11-07" } });
    expect(form.textContent).toContain("On Saturdays");
    await within(form).findByRole("option", { name: "Europe" });
    fireEvent.change(within(form).getByLabelText("Time zone"), { target: { value: "Europe" } });
    fireEvent.change(within(form).getByLabelText("City"), { target: { value: "Europe/Brussels" } });
    fireEvent.click(screen.getByTestId("schedule-save"));
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", `${base}/schedule`)).toEqual([
        { every_weeks: 2, first: "2026-11-07", start: "20:00", end: "22:00", time_zone: "Europe/Brussels", changes: [] },
      ]),
    );
    rerender(<TableSchedule campaign={{ ...campaign, schedule, next_sessions: [session] }} />);
    expect(screen.getByTestId("schedule-preview").textContent).toContain("Every 2 weeks on Saturday");
    fireEvent.click(screen.getByTestId("schedule-clear"));
    await waitFor(() => expect(sent(fetchMock, "PUT", `${base}/schedule`)).toHaveLength(2));
    expect(sent(fetchMock, "PUT", `${base}/schedule`)[1]).toBeNull();
  });
});

describe("NextSessionControls", () => {
  it("skips the next session, moves it in the schedule's time zone, and undoes a move", async () => {
    const fetchMock = stubFetch({ [`POST ${base}/schedule/next`]: () => json(200, { schedule, next_sessions: [session] }) });
    const { rerender } = renderWith(<NextSessionControls campaignId={CAMPAIGN} schedule={schedule} sessions={[session]} />);
    fireEvent.click(screen.getByTestId("next-skip"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/schedule/next`)).toEqual([{ skip: true }]));
    fireEvent.click(screen.getByTestId("next-move"));
    const when = screen.getByLabelText("New date and time (Europe/Brussels)") as HTMLInputElement;
    expect(when.value, "the start, in Brussels time").toBe("2026-11-07T20:00");
    fireEvent.change(when, { target: { value: "2026-11-08T19:00" } });
    fireEvent.click(screen.getByTestId("next-move-save"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/schedule/next`)[1]).toEqual({ to: "2026-11-08T19:00" }));
    rerender(<NextSessionControls campaignId={CAMPAIGN} schedule={schedule} sessions={[{ ...session, moved: true }]} />);
    fireEvent.click(screen.getByTestId("next-reset"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/schedule/next`)[2]).toEqual({ reset: true }));
  });

  it("offers to tell the players by email only when mail goes, unticked, and says how many were told", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: true }),
      [`POST ${base}/schedule/next`]: () => json(200, { schedule, next_sessions: [session], emailed: 3 }),
    });
    renderWith(<NextSessionControls campaignId={CAMPAIGN} schedule={schedule} sessions={[session]} />);
    const tick = (await screen.findByLabelText("Tell the players by email")) as HTMLInputElement;
    expect(tick.checked).toBe(false);
    expect(screen.queryByTestId("next-note")).toBeNull();
    fireEvent.click(screen.getByTestId("next-skip"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/schedule/next`)).toEqual([{ skip: true }]));
    await waitFor(() => expect((screen.getByTestId("next-skip") as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByTestId("next-told"), "no email asked: no count").toBeNull();
    fireEvent.click(tick);
    fireEvent.change(screen.getByTestId("next-note"), { target: { value: " Flu, sorry. " } });
    fireEvent.click(screen.getByTestId("next-skip"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/schedule/next`)[1]).toEqual({ skip: true, email: { note: "Flu, sorry." } }),
    );
    expect((await screen.findByTestId("next-told")).textContent).toBe("Players told by email: 3");
  });

  it("sends the line with a move too, and hides the choice without mail", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: true }),
      [`POST ${base}/schedule/next`]: () => json(200, { schedule, next_sessions: [session], emailed: 0 }),
    });
    const { unmount } = renderWith(<NextSessionControls campaignId={CAMPAIGN} schedule={schedule} sessions={[session]} />);
    fireEvent.click(await screen.findByLabelText("Tell the players by email"));
    fireEvent.click(screen.getByTestId("next-move"));
    fireEvent.change(screen.getByLabelText("New date and time (Europe/Brussels)"), { target: { value: "2026-11-08T19:00" } });
    fireEvent.click(screen.getByTestId("next-move-save"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `${base}/schedule/next`)).toEqual([{ to: "2026-11-08T19:00", email: { note: "" } }]),
    );
    expect((await screen.findByTestId("next-told")).textContent, "asked, so told even at none").toBe(
      "Players told by email: 0",
    );
    unmount();
    stubFetch({ "GET /api/mail/status": () => json(200, { enabled: false }) });
    renderWith(<NextSessionControls campaignId={CAMPAIGN} schedule={schedule} sessions={[session]} />);
    expect(screen.getByTestId("next-skip")).toBeTruthy();
    expect(screen.queryByLabelText("Tell the players by email")).toBeNull();
  });

  it("shows nothing without a schedule", () => {
    stubFetch({});
    renderWith(<NextSessionControls campaignId={CAMPAIGN} schedule={null} sessions={[]} />);
    expect(screen.queryByTestId("next-session-controls")).toBeNull();
  });
});
