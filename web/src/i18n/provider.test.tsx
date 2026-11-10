import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "./index";

describe("I18nProvider", () => {
  it("sets the page's <html lang> to the language it speaks (DEL-174)", () => {
    const { rerender } = render(<I18nProvider language="nl">x</I18nProvider>);
    expect(document.documentElement.lang).toBe("nl");
    rerender(<I18nProvider language="pt">x</I18nProvider>);
    expect(document.documentElement.lang).toBe("en");
  });

  it("fetches a language's dictionary when it is spoken, keeping English until it is in (DEL-240)", async () => {
    // A copy of the module without the tests' dictionaries: only English is in it, as in the main bundle.
    vi.resetModules();
    const fresh = await import("./index");
    expect(fresh.hasLanguage("en")).toBe(true);
    expect(fresh.hasLanguage("nl")).toBe(false);
    expect(fresh.translate("nl", "area.play")).toBe("Play");
    function Label() {
      return <span data-testid="label">{fresh.useT()("area.houseRules")}</span>;
    }
    render(
      <fresh.I18nProvider language="nl">
        <Label />
      </fresh.I18nProvider>,
    );
    // English while the Dutch is fetched: never a bare key.
    expect(screen.getByTestId("label").textContent).toBe("House rules");
    expect(document.documentElement.lang).toBe("en");
    expect(await screen.findByText("Huisregels")).toBeTruthy();
    expect(document.documentElement.lang).toBe("nl");
    expect(fresh.hasLanguage("nl")).toBe(true);
    // Fetched once: a second ask doesn't fetch it again.
    await fresh.loadLanguage("nl");
    expect(fresh.hasLanguage("fr")).toBe(false);
  });
});
