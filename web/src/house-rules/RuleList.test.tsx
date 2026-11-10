import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { HouseRule } from "../api";
import { I18nProvider } from "../i18n";
import RuleList from "./RuleList";

const base: Pick<HouseRule, "body_md" | "phases" | "ruleset" | "setting" | "enabled"> = {
  body_md: "",
  phases: [],
  ruleset: null,
  setting: null,
  enabled: true,
};
const rules: HouseRule[] = [
  { ...base, id: "hr_1", title: "Lizardfolk", kind: "race", subject: "lizardfolk", body_md: "Bite 1d6." },
  { ...base, id: "hr_2", title: "Max HP", kind: "general", subject: null },
  { ...base, id: "hr_3", title: "Kobold", kind: "race", subject: "kobold", enabled: false },
  { ...base, id: "hr_4", title: "The Hawkblade", kind: "item", subject: "the-hawkblade" },
];

describe("RuleList", () => {
  it("groups the rules by kind, and filters them", () => {
    const onSelect = vi.fn();
    render(
      <I18nProvider language="en">
        <RuleList rules={rules} selectedId="hr_2" onSelect={onSelect} />
      </I18nProvider>,
    );
    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual(["General (1)", "Races (2)", "Items (1)"]);
    expect(screen.getByRole("button", { name: /Max HP/ }).getAttribute("aria-current")).toBe("true");
    expect(screen.getByRole("button", { name: /Kobold/ }).textContent).toContain("off");

    fireEvent.change(screen.getByLabelText("Filter rules"), { target: { value: "bite" } });
    expect(screen.getAllByRole("heading").map((h) => h.textContent)).toEqual(["Races (1)"]);
    fireEvent.click(screen.getByRole("button", { name: /Lizardfolk/ }));
    expect(onSelect).toHaveBeenCalledWith("hr_1");

    fireEvent.change(screen.getByLabelText("Filter rules"), { target: { value: "zzz" } });
    expect(screen.getByText("No rule matches “zzz”.")).toBeTruthy();
  });
});
