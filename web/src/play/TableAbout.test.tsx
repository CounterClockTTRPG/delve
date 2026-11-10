import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import TableAbout from "./TableAbout";

function renderAbout(about: Parameters<typeof TableAbout>[0]["about"]) {
  return render(
    <I18nProvider language="en">
      <TableAbout about={about} />
    </I18nProvider>,
  );
}

describe("TableAbout (DEL-204)", () => {
  it("shows the description, the places taken and the house rules, each folded", () => {
    renderAbout({
      description: "We *listen* to each other.",
      slots: 4,
      taken: 3,
      house_rules: [{ id: "hr_1", title: "Max HP at first level", body_md: "Roll **nothing** at level 1." }],
    });
    const about = screen.getByTestId("table-about");
    expect(about.querySelector(".table-description em")?.textContent).toBe("listen");
    expect(screen.getByTestId("table-places").textContent).toBe("3 of 4 places taken");
    const all = screen.getByText("House rules in effect (1)").closest("details")!;
    expect(all.open, "the house rules fold together").toBe(false);
    fireEvent.click(screen.getByText("House rules in effect (1)"));
    const rule = screen.getByText("Max HP at first level").closest("details")!;
    expect(rule.open).toBe(false);
    fireEvent.click(screen.getByText("Max HP at first level"));
    expect(rule.querySelector("strong")?.textContent).toBe("nothing");
  });

  it("says when every place is taken", () => {
    renderAbout({ slots: 2, taken: 2, description: "", house_rules: [] });
    expect(screen.getByTestId("table-places").textContent).toBe("The table is full: 2 of 2 places taken");
    expect(screen.getByTestId("table-places").className).toContain("full");
  });

  it("shows nothing for a table with no description, no limit and no house rules", () => {
    renderAbout({ slots: null, taken: 1, description: " ", house_rules: [] });
    expect(screen.queryByTestId("table-about")).toBeNull();
  });

  it("links a seat's own scheduled table to its calendar file, and no other (DEL-236)", () => {
    const schedule = { every_weeks: 1, first: "2026-11-07", start: "20:00", end: "22:00", time_zone: "Europe/Brussels", changes: [] };
    const about = { description: "", house_rules: [], slots: null, taken: 0, schedule, next_sessions: [] };
    const seated = render(
      <I18nProvider language="en">
        <TableAbout about={about} calendarFor="cmp_00000000000a" />
      </I18nProvider>,
    );
    const link = screen.getByTestId("schedule-calendar");
    expect(link.getAttribute("href")).toBe("/api/campaigns/cmp_00000000000a/schedule.ics");
    expect(link.textContent).toContain("Add the sessions to your calendar");
    seated.unmount();
    renderAbout(about);
    expect(screen.queryByTestId("schedule-calendar"), "the join page and Find a table have no seat yet").toBeNull();
  });
});
