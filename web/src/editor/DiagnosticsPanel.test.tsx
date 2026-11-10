import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import type { Diagnostic } from "./types";

const found = [
  { severity: "error", line: 3, column: 5, message: "Unknown room." },
  { severity: "warning", line: 0, column: 0, message: "No title." },
] as Diagnostic[];

describe("DiagnosticsPanel", () => {
  it("each problem is a button that jumps to it, so the keyboard reaches it too", () => {
    const onJump = vi.fn();
    render(
      <I18nProvider language="en">
        <DiagnosticsPanel diagnostics={found} onJump={onJump} />
      </I18nProvider>,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["3:5Unknown room.", "—No title."]);
    expect(buttons[0].getAttribute("type")).toBe("button");
    fireEvent.click(buttons[1]);
    expect(onJump).toHaveBeenCalledWith(found[1]);
  });

  it("without onJump, lists them with no buttons", () => {
    render(
      <I18nProvider language="en">
        <DiagnosticsPanel diagnostics={found} />
      </I18nProvider>,
    );
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.getByText("Unknown room.")).toBeTruthy();
  });
});
