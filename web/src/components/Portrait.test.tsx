import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RENDER_STYLES, generate } from "portraitgen";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import commit from "../../vendor/portraitgen/COMMIT?raw";
import { base, json, playState, stubFetch } from "../play/testing";
import Portrait, { portraitSvg } from "./Portrait";
import { PORTRAIT_STYLES, PortraitStyleProvider, usePortraitStyle } from "./portraitStyle";

afterEach(() => {
  vi.unstubAllGlobals();
});

const CAMPAIGN = "cmp_00000000000a";
const traits = { kind: "traits", describe: "a stout old male dwarf", seed: "chr_00000000000a" } as const;

/** The drawing's SVG with its own id prefix (`pg…`, before each id's first dash) written as `ID`. */
function drawing(element: Element): string {
  const html = element.innerHTML;
  const prefix = /id="([^"-]+)-/.exec(html)?.[1] ?? "";
  return html.replaceAll(prefix, "ID");
}

/** An SVG as the page holds it once drawn. */
function asDrawn(svg: string): string {
  const box = document.createElement("span");
  box.innerHTML = svg;
  return box.innerHTML;
}

/** The campaign's play state says its portrait style. */
function inStyle(style: string, children: ReactNode) {
  stubFetch({ [`GET ${base}/play/state`]: () => json(200, { ...playState(), portrait_style: style }) });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PortraitStyleProvider campaignId={CAMPAIGN}>{children}</PortraitStyleProvider>
    </QueryClientProvider>,
  );
}

function StyleName() {
  return <output>{usePortraitStyle()}</output>;
}

describe("Portrait", () => {
  it("vendors portraitgen at the pinned commit", () => {
    expect(commit.trim()).toBe("7ba15abb85d64e1f14ed434db345ca047af1425e");
  });

  it("draws a minotaur for a minotaur's description (portraitgen 7ba15ab)", () => {
    expect(generate({ describe: "a male minotaur fighter", seed: "chr_00000000000m" }).archetype).toBe("minotaur");
  });

  it("renders the same SVG for the same description and seed", () => {
    const first = portraitSvg(traits, 64, "pg-a");
    expect(first).toContain("<svg");
    expect(portraitSvg(traits, 64, "pg-a")).toBe(first);
    expect(portraitSvg({ ...traits, seed: "chr_00000000000b" }, 64, "pg-a")).not.toBe(first);
  });

  it("draws a traits portrait as SVG, with ids of its own in each instance", () => {
    render(
      <>
        <Portrait campaignId={CAMPAIGN} portrait={traits} name="Ash" size={48} />
        <Portrait campaignId={CAMPAIGN} portrait={traits} name="Ash" size={48} />
      </>,
    );
    const drawn = screen.getAllByRole("img", { name: "Ash" });
    expect(drawn).toHaveLength(2);
    const [one, two] = drawn.map((d) => d.querySelector("svg"));
    expect(one).not.toBeNull();
    const ids = (svg: SVGSVGElement | null) => [...(svg?.querySelectorAll("[id]") ?? [])].map((e) => e.id);
    expect(ids(one).length).toBeGreaterThan(0);
    expect(ids(one).filter((id) => ids(two).includes(id))).toEqual([]);
  });

  it("shows a painted portrait from the pictures route", () => {
    render(<Portrait campaignId={CAMPAIGN} portrait={{ kind: "image", image_id: "img_00000000000a" }} name="Birch" size={48} />);
    const img = screen.getByRole("img", { name: "Birch" });
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/pictures/img_00000000000a`);
  });

  it("enlarges a drawn portrait in a dialog on a click, without the click reaching what holds it", () => {
    const held = vi.fn();
    render(
      <div onClick={held}>
        <Portrait campaignId={CAMPAIGN} portrait={traits} name="Ash" size={40} />
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Enlarge Ash's portrait" }));
    expect(held).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Ash" });
    const big = within(dialog).getByRole("img", { name: "Ash" });
    expect(big.querySelector("svg")?.getAttribute("width")).toBe("480");
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("enlarges a painted portrait, and closes on a click on it", () => {
    render(<Portrait campaignId={CAMPAIGN} portrait={{ kind: "image", image_id: "img_00000000000a" }} name="Birch" size={48} />);
    fireEvent.click(screen.getByRole("button", { name: "Enlarge Birch's portrait" }));
    const dialog = screen.getByRole("dialog", { name: "Birch" });
    const big = within(dialog).getByRole("img", { name: "Birch" });
    expect(big.getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/pictures/img_00000000000a`);
    fireEvent.click(big);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers nothing to enlarge for an initial", () => {
    render(<Portrait campaignId={CAMPAIGN} portrait={null} name="Cedar" size={40} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("lists portraitgen's render styles, illustrated first", () => {
    expect([...PORTRAIT_STYLES].sort()).toEqual(Object.keys(RENDER_STYLES).sort());
    expect(PORTRAIT_STYLES[0]).toBe("illustrated");
  });

  it("draws in the campaign's portrait style", async () => {
    inStyle(
      "inkwash",
      <>
        <StyleName />
        <Portrait campaignId={CAMPAIGN} portrait={traits} name="Ash" size={48} />
      </>,
    );
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("inkwash"));
    const inkwash = portraitSvg(traits, 48, "ID", { style: "inkwash" });
    expect(inkwash).not.toBe(portraitSvg(traits, 48, "ID"));
    expect(drawing(screen.getByRole("img", { name: "Ash" }))).toBe(asDrawn(inkwash));
  });

  it("draws as before without a style: illustrated, the portrait's own look", () => {
    render(<Portrait campaignId={CAMPAIGN} portrait={traits} name="Ash" size={48} />);
    expect(drawing(screen.getByRole("img", { name: "Ash" }))).toBe(asDrawn(portraitSvg(traits, 48, "ID")));
    expect(portraitSvg(traits, 48, "ID", { style: "illustrated" })).toBe(portraitSvg(traits, 48, "ID"));
  });

  it("takes a style of its own over the campaign's, and passes the emotes on", async () => {
    inStyle(
      "inkwash",
      <>
        <StyleName />
        <Portrait campaignId={CAMPAIGN} portrait={traits} name="Ash" size={48} style="pixel" emotes={["talk"]} say="Hello there" once />
      </>,
    );
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("inkwash"));
    const options = { style: "pixel", emotes: ["talk"], say: "Hello there", once: true };
    expect(drawing(screen.getByRole("img", { name: "Ash" }))).toBe(asDrawn(portraitSvg(traits, 48, "ID", options)));
  });

  it("shows a painted portrait as it is, in any style", async () => {
    inStyle(
      "inkwash",
      <>
        <StyleName />
        <Portrait campaignId={CAMPAIGN} portrait={{ kind: "image", image_id: "img_00000000000a" }} name="Birch" size={48} />
      </>,
    );
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("inkwash"));
    const img = screen.getByRole("img", { name: "Birch" });
    expect(img.tagName).toBe("IMG");
    expect(img.getAttribute("src")).toBe(`/api/campaigns/${CAMPAIGN}/pictures/img_00000000000a`);
  });

  it("shows the initial without a portrait", () => {
    const { container } = render(<Portrait campaignId={CAMPAIGN} portrait={null} name="Cedar" size={48} />);
    expect(container.textContent).toBe("C");
    expect(container.querySelector("svg, img")).toBeNull();
  });
});
