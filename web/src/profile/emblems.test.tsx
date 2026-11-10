import { render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { Emblem, EMBLEMS } from "./emblems";

/** The server's list, `delve.domain.accounts.EMBLEMS`, read from its source. */
function serverEmblems(): string[] {
  const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../../src/delve/domain/accounts.py"), "utf8");
  const list = /^EMBLEMS = \(([^)]*)\)/m.exec(source)![1];
  return [...list.matchAll(/"([a-z]+)"/g)].map((m) => m[1]);
}

describe("emblems", () => {
  it("has the twelve emblems, in the server's order", () => {
    expect(EMBLEMS).toHaveLength(12);
    expect([...EMBLEMS]).toEqual(serverEmblems());
  });

  it("each is an inline SVG with no href", () => {
    for (const name of EMBLEMS) {
      const { container, unmount } = render(<Emblem name={name} title={name} />);
      const svg = container.querySelector("svg")!;
      expect(svg.getAttribute("viewBox")).toBe("0 0 64 64");
      expect(svg.getAttribute("fill")).toBe("currentColor");
      expect(svg.querySelector("title")?.textContent).toBe(name);
      expect(svg.querySelectorAll("path").length, name).toBeGreaterThanOrEqual(2);
      expect(container.innerHTML, name).not.toMatch(/href|url\(|<image|<use/);
      unmount();
    }
  });

  it("draws a different charge for each", () => {
    const charges = EMBLEMS.map((name) => {
      const { container, unmount } = render(<Emblem name={name} />);
      const d = container.querySelector("path.emblem-charge")!.getAttribute("d");
      unmount();
      return d;
    });
    expect(new Set(charges).size).toBe(12);
  });
});
