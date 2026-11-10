import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { LOOK_KEY, applyLook, editorTheme, readLook, useLook, useNoLook } from "./looks";

const here = dirname(fileURLToPath(import.meta.url));

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  delete document.documentElement.dataset.look;
});

describe("looks", () => {
  test("an unknown or unreadable choice is Delve today", () => {
    expect(readLook()).toBe("delve");
    localStorage.setItem(LOOK_KEY, "neon");
    expect(readLook()).toBe("delve");
    localStorage.setItem(LOOK_KEY, "dark-dungeon");
    expect(readLook()).toBe("dark-dungeon");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readLook()).toBe("delve");
  });

  test("choosing a look sets the attribute and remembers it", () => {
    const { result } = renderHook(() => useLook());
    expect(result.current[0]).toBe("delve");
    act(() => result.current[1]("gold-wood"));
    expect(result.current[0]).toBe("gold-wood");
    expect(document.documentElement.dataset.look).toBe("gold-wood");
    expect(localStorage.getItem(LOOK_KEY)).toBe("gold-wood");
  });

  test("Delve today sets no attribute", () => {
    applyLook("gold-wood");
    expect(document.documentElement.getAttribute("data-look")).toBe("gold-wood");
    applyLook("delve");
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
  });

  test("a storage that throws on write still switches the page", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    const { result } = renderHook(() => useLook());
    act(() => result.current[1]("dark-dungeon"));
    expect(document.documentElement.dataset.look).toBe("dark-dungeon");
    expect(result.current[0]).toBe("dark-dungeon");
  });

  test("another tab's choice is followed", () => {
    const { result } = renderHook(() => useLook());
    localStorage.setItem(LOOK_KEY, "gold-wood");
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: LOOK_KEY, newValue: "gold-wood" }));
    });
    expect(result.current[0]).toBe("gold-wood");
    expect(document.documentElement.dataset.look).toBe("gold-wood");
  });

  test("look.js sets the attribute before the app loads", () => {
    const script = readFileSync(join(here, "../../public/look.js"), "utf8");
    const run = (stored: string | null, throws = false, pathname = "/campaigns") => {
      const doc = document.implementation.createHTMLDocument("fresh");
      const win = {
        location: { pathname },
        localStorage: {
          getItem: (key: string) => {
            if (throws) throw new Error("SecurityError");
            return key === LOOK_KEY ? stored : null;
          },
        },
      };
      new Function("window", "document", script)(win, doc);
      return doc.documentElement.getAttribute("data-look");
    };
    expect(run("dark-dungeon")).toBe("dark-dungeon");
    expect(run("gold-wood")).toBe("gold-wood");
    expect(run("delve")).toBeNull();
    expect(run("<junk>")).toBeNull();
    expect(run(null)).toBeNull();
    expect(run("gold-wood", true)).toBeNull();
    expect(run("gold-wood", false, "/modules/mod_x/print")).toBeNull();
    expect(run("dark-dungeon", false, "/maps/mod_x/crypt/print")).toBeNull();
    expect(run("dark-dungeon", false, "/novels/nov_x/print")).toBeNull();
    expect(run("dark-dungeon", false, "/modules/printing-press")).toBe("dark-dungeon");
  });

  test("index.html runs look.js before any stylesheet, as a file", () => {
    const html = readFileSync(join(here, "../../index.html"), "utf8");
    const head = html.slice(0, html.indexOf("</head>"));
    expect(head).toContain('<script src="/look.js"></script>');
    expect(head).not.toMatch(/<link[^>]*stylesheet/);
  });

  test("the editor goes dark in the new looks", () => {
    expect(editorTheme("delve")).toBe("dmap-paper");
    expect(editorTheme("gold-wood")).toBe("dmap-night");
    expect(editorTheme("dark-dungeon")).toBe("dmap-night");
  });

  test("a print view takes the look off while it is open, and puts it back after", () => {
    applyLook("dark-dungeon");
    const first = renderHook(() => useNoLook());
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
    const second = renderHook(() => useNoLook());
    first.unmount();
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
    second.unmount();
    expect(document.documentElement.dataset.look).toBe("dark-dungeon");
  });

  test("a print view opened first puts the stored look back when it closes", () => {
    localStorage.setItem(LOOK_KEY, "gold-wood");
    const view = renderHook(() => useNoLook());
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
    view.unmount();
    expect(document.documentElement.dataset.look).toBe("gold-wood");
  });
});
