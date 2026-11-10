import { describe, expect, it } from "vitest";
import { hpLeft, hpTone, withTokenFaces } from "./tokenFaces";

// Two tokens as `delve.maps.tokens` and the renderer's `_marker` draw them: a disc in the side's colour, the initial,
// and the caption under it.
function marker(name: string, fill: string, x: number, label: string) {
  return (
    `<g class="marker" data-name="${name}" data-tag="party" data-location="room.hall">` +
    `<circle cx="${x}" cy="-3" r="0.4" fill="${fill}" stroke="#222" stroke-width="0.072"/>` +
    `<text x="${x}" y="-3" font-size="0.42" fill="#fff" text-anchor="middle" dominant-baseline="central">${label[0]}</text>` +
    `<text class="caption" x="${x}" y="-2.26">${label}</text></g>`
  );
}

const MAP =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 -10 10 10"><g class="markers">` +
  marker("chr_00000000000a", "#2c7be5", 2, "Mirela") +
  marker("chr_00000000000b", "#2c7be5", 3, "Tansy") +
  marker("chr_00000000000c", "#2db469", 4, "Ulf") +
  marker("mon_1", "#c43232", 5, "Goblin 1") +
  `</g></svg>`;

const look = { campaignId: "cmp_000000000001", style: "illustrated", idPrefix: "mapA" };
const faces = {
  chr_00000000000a: { portrait: { kind: "traits", describe: "a young elven wizard", seed: "mirela" } as const, hp: 9, hpMax: 12 },
  chr_00000000000b: { portrait: { kind: "image", image_id: "img_000000000007" } as const, hp: 2, hpMax: 10 },
  chr_00000000000c: { portrait: null, hp: 5, hpMax: 10 },
};

function parsed(svg: string) {
  return new DOMParser().parseFromString(svg, "image/svg+xml");
}

const token = (doc: Document, name: string) => doc.querySelector(`g.marker[data-name="${name}"]`)!;

describe("withTokenFaces", () => {
  it("puts a drawn portrait in the token, clipped to it, in a ring of its side's colour", () => {
    const doc = parsed(withTokenFaces(MAP, faces, look));
    const mirela = token(doc, "chr_00000000000a");
    expect(mirela.getAttribute("data-face")).toBe("portrait");
    const face = mirela.querySelector("g.token-face")!;
    expect(face.getAttribute("clip-path")).toBe("url(#mapAt0clip)");
    expect(mirela.querySelector("clipPath#mapAt0clip circle")!.getAttribute("r")).toBe("0.4");
    const drawn = face.querySelector("svg")!;
    expect([drawn.getAttribute("x"), drawn.getAttribute("y"), drawn.getAttribute("width")]).toEqual(["1.6", "-3.4", "0.8"]);
    // The portrait's own ids carry this token's prefix, apart from every other drawing's.
    const ids = [...drawn.querySelectorAll("[id]")].map((e) => e.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(ids.every((id) => id.startsWith("mapAt0"))).toBe(true);
    const ring = [...mirela.querySelectorAll(":scope > circle")].find((c) => c.getAttribute("stroke") === "#2c7be5");
    expect(ring).toBeTruthy();
    // The initial makes way; the caption stays.
    expect([...mirela.querySelectorAll(":scope > text")].map((e) => e.textContent)).toEqual(["Mirela"]);
  });

  it("shows a painted portrait from the pictures route", () => {
    const tansy = token(parsed(withTokenFaces(MAP, faces, look)), "chr_00000000000b");
    expect(tansy.querySelector("image")!.getAttribute("href")).toBe("/api/campaigns/cmp_000000000001/pictures/img_000000000007");
  });

  it("draws an arc of the hit points left, coloured by how hurt", () => {
    const doc = parsed(withTokenFaces(MAP, faces, look));
    const arc = (name: string) => token(doc, name).querySelector(".token-hp")!;
    expect(arc("chr_00000000000a").getAttribute("stroke-dasharray")).toBe("75 100");
    expect(arc("chr_00000000000a").getAttribute("stroke")).toBe("#3fbf5f");
    expect(arc("chr_00000000000b").getAttribute("stroke")).toBe("#e0412b");
    expect(arc("chr_00000000000c").getAttribute("stroke")).toBe("#e0a92e");
  });

  it("keeps the initial of a character without a portrait, and leaves an enemy as it was", () => {
    const doc = parsed(withTokenFaces(MAP, faces, look));
    const ulf = token(doc, "chr_00000000000c");
    expect(ulf.getAttribute("data-face")).toBe("initial");
    expect(ulf.querySelector("circle[fill='#2db469']")).not.toBeNull();
    expect(ulf.querySelector(":scope > text")!.textContent).toBe("U");
    const goblin = token(doc, "mon_1");
    expect(goblin.hasAttribute("data-face")).toBe(false);
    expect(goblin.querySelector(".token-hp")).toBeNull();
    expect(goblin.querySelectorAll("circle")).toHaveLength(1);
  });

  it("answers a map without tokens, or without faces, as it came", () => {
    const bare = `<svg xmlns="http://www.w3.org/2000/svg"><g class="party"/></svg>`;
    expect(withTokenFaces(bare, faces, look)).toBe(bare);
    expect(withTokenFaces(MAP, {}, look)).toBe(MAP);
    expect(withTokenFaces("<svg class=\"marker\"", faces, look)).toBe("<svg class=\"marker\"");
  });
});

describe("hit points left", () => {
  it("is a share from 0 to 1, or nothing without a maximum", () => {
    expect(hpLeft({ hp: 6, hpMax: 12 })).toBe(0.5);
    expect(hpLeft({ hp: -3, hpMax: 12 })).toBe(0);
    expect(hpLeft({ hp: 15, hpMax: 12 })).toBe(1);
    expect(hpLeft({ hp: 4, hpMax: 0 })).toBeNull();
    expect(hpLeft(undefined)).toBeNull();
    expect([hpTone(0.6), hpTone(0.5), hpTone(0.25), hpTone(0)]).toEqual(["healthy", "wounded", "critical", "critical"]);
  });
});
