import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Bundle, HouseRule } from "../api";
import { I18nProvider } from "../i18n";
import BundleEditor from "./BundleEditor";

const rule = (id: string, title: string): HouseRule => ({
  id,
  title,
  body_md: "",
  kind: "general",
  phases: ["always"],
  ruleset: null,
  setting: null,
  subject: null,
  enabled: true,
});
const rules = [
  rule("hr_a", "Max HP"),
  rule("hr_b", "4d6 drop lowest"),
  rule("hr_c", "Ignore level caps"),
  rule("hr_d", "Lizardfolk"),
];
const table: Bundle = {
  id: "hb_1",
  title: "My table",
  description_md: "Tuesdays.",
  rule_ids: ["hr_a", "hr_b", "hr_c"],
};

function renderEditor() {
  const onSave = vi.fn();
  render(
    <I18nProvider language="en">
      <BundleEditor bundle={table} rules={rules} onSave={onSave} />
    </I18nProvider>,
  );
  return onSave;
}

const order = () =>
  within(screen.getByRole("list", { name: "Rules in this bundle" }))
    .getAllByRole("listitem")
    .map((li) => li.querySelector(".bundle-rule-title")?.textContent);

describe("BundleEditor", () => {
  it("reorders with the arrows and saves the order", () => {
    const onSave = renderEditor();
    expect(order()).toEqual(["Max HP", "4d6 drop lowest", "Ignore level caps"]);
    expect((screen.getByRole("button", { name: "Move Max HP up" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Move Ignore level caps down" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    fireEvent.click(screen.getByRole("button", { name: "Move Ignore level caps up" }));
    fireEvent.click(screen.getByRole("button", { name: "Move Max HP down" }));
    expect(order()).toEqual(["Ignore level caps", "Max HP", "4d6 drop lowest"]);
    fireEvent.click(screen.getByRole("button", { name: "Save bundle" }));
    expect(onSave).toHaveBeenCalledWith({
      title: "My table",
      description_md: "Tuesdays.",
      rule_ids: ["hr_c", "hr_a", "hr_b"],
    });
  });

  it("adds and removes rules", () => {
    const onSave = renderEditor();
    const add = screen.getByLabelText("Add a rule") as HTMLSelectElement;
    expect([...add.options].map((o) => o.textContent)).toEqual(["Lizardfolk"]);
    fireEvent.change(add, { target: { value: "hr_d" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove 4d6 drop lowest" }));
    expect(order()).toEqual(["Max HP", "Ignore level caps", "Lizardfolk"]);
    fireEvent.click(screen.getByRole("button", { name: "Save bundle" }));
    expect(onSave.mock.calls[0][0].rule_ids).toEqual(["hr_a", "hr_c", "hr_d"]);
  });
});
