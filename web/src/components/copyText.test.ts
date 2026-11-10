import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./copyText";

afterEach(() => vi.unstubAllGlobals());

describe("copyText", () => {
  it("copies with the clipboard", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    expect(await copyText("the link")).toBe(true);
    expect(writeText).toHaveBeenCalledWith("the link");
  });

  it("says it failed when the clipboard refuses", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => Promise.reject(new Error("denied"))) } });
    expect(await copyText("the link")).toBe(false);
  });

  it("without a clipboard (plain http), tries the selection copy and says whether it worked", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    const original = document.execCommand;
    const execCommand = vi.fn(() => false);
    document.execCommand = execCommand;
    try {
      expect(await copyText("the link")).toBe(false);
      execCommand.mockReturnValue(true);
      expect(await copyText("the link")).toBe(true);
      expect(execCommand).toHaveBeenCalledWith("copy");
      expect(document.querySelector("textarea")).toBeNull();
    } finally {
      document.execCommand = original;
    }
  });
});
