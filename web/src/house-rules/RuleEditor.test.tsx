import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { HouseRule } from "../api";
import { I18nProvider } from "../i18n";
import RuleEditor, { Markdown } from "./RuleEditor";

const maxHp: HouseRule = {
  id: "hr_00000000000a",
  title: "Max HP",
  body_md: "Characters start at **maximum** HP.",
  kind: "general",
  phases: ["character-creation"],
  ruleset: null,
  setting: null,
  subject: null,
  enabled: true,
};

function renderEditor(rule = maxHp, language = "en") {
  const onSave = vi.fn();
  render(
    <I18nProvider language={language}>
      <RuleEditor rule={rule} onSave={onSave} />
    </I18nProvider>,
  );
  return onSave;
}

describe("RuleEditor", () => {
  it("saves its phases, in their order, with the other fields", () => {
    const onSave = renderEditor();
    const chips = within(screen.getByRole("group", { name: "When it applies" }));
    expect(chips.getByRole("button", { name: "Character creation" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(chips.getByRole("button", { name: "Always" }));
    fireEvent.click(chips.getByRole("button", { name: "Level up" }));
    fireEvent.click(chips.getByRole("button", { name: "Character creation" }));
    expect(chips.getByRole("button", { name: "Character creation" }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.change(screen.getByLabelText("Setting"), { target: { value: " greyhawk " } });
    fireEvent.change(screen.getByLabelText("Kind"), { target: { value: "behaviour" } });
    fireEvent.click(screen.getByLabelText("Enabled"));
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    expect(onSave).toHaveBeenCalledWith({
      title: "Max HP",
      body_md: "Characters start at **maximum** HP.",
      kind: "behaviour",
      phases: ["level-up", "always"],
      ruleset: null,
      setting: "greyhawk",
      subject: null,
      enabled: false,
    });
  });

  it("won't save without a title", () => {
    const onSave = renderEditor();
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "  " } });
    const save = screen.getByRole("button", { name: "Save rule" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(save);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("previews the Markdown", () => {
    renderEditor();
    fireEvent.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByText("maximum").tagName).toBe("STRONG");
  });

  it("speaks Dutch", () => {
    renderEditor(maxHp, "nl");
    expect(screen.getByRole("button", { name: "Regel opslaan" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Personage maken" })).toBeTruthy();
  });
});

describe("Markdown", () => {
  it("renders headings, lists, tables and emphasis as elements, never as HTML", () => {
    const { container } = render(
      <Markdown
        source={
          "## Special Rules\n\n- **Flight.** Move 6, *Fly 36*.\n- Bite `1d6`\n\n| Ability | Min |\n|---|---|\n| Str | 3 |\n\n<img src=x onerror=alert(1)>"
        }
      />,
    );
    expect(container.querySelector("h4")?.textContent).toBe("Special Rules");
    expect([...container.querySelectorAll("li")].map((li) => li.textContent)).toEqual([
      "Flight. Move 6, Fly 36.",
      "Bite 1d6",
    ]);
    expect(container.querySelector("li strong")?.textContent).toBe("Flight.");
    expect(container.querySelector("li em")?.textContent).toBe("Fly 36");
    expect(container.querySelector("code")?.textContent).toBe("1d6");
    expect([...container.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["Ability", "Min"]);
    expect([...container.querySelectorAll("td")].map((td) => td.textContent)).toEqual(["Str", "3"]);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });
});
