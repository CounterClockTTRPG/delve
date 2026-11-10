import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModuleSource } from "../api";
import { I18nProvider } from "../i18n";
import ModuleDetail from "./ModuleDetail";
import MapPrint from "./MapPrint";
import ModulePrint from "./ModulePrint";
import styles from "./ModulePrint.module.css";

const MODULE = "mod_cccccccccccc";
const module = {
  id: MODULE,
  title: "The Crypt of Saint Vellis",
  metadata: {
    authors: ["Mara Quill", { name: "Ot Venn", role: "cartographer" }],
    party: { levels: { min: 1, max: 3 }, size: 4 },
    setting: "The Vale",
    cover: "asset:cover",
  },
  maps: [
    { name: "crypt", role: "map", is_default: true, source: "map crypt {}" },
    { name: "core.dmap", role: "library", is_default: false, source: "" },
  ],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
};

function source(): ModuleSource {
  return {
    texts: [
      { id: "intro", title: "Introduction", audience: "player", map: null, markdown: "# The Crypt\n\nIntro text.\n" },
      {
        id: "crypt-key",
        title: "Keyed encounters",
        audience: "gm",
        map: "crypt",
        markdown:
          "## C1. Entry Hall {#c1}\n\n> Dust lies thick on the stairs.\n\nBones. [[npc:brother-ansel]] waits.\n\n> A quote of his.\n\n" +
          "## Background\n\n> Built by monks.\n\nLore.\n\n> A note, not read aloud.\n",
      },
    ],
    entities: {
      npcs: [
        {
          id: "brother-ansel",
          name: "Brother Ansel",
          summary: "The last monk.",
          stats: { adnd2e: { class: "Priest", level: 3, ac: 5, hp: 14, line: "AC 5; MV 12; P3; hp 14; #AT 1; D 1-6" } },
        },
      ],
      encounters: [
        {
          id: "skeletons",
          name: "Skeleton guard",
          key: "c1",
          stats: { adnd2e: { line: "AC 7; MV 12; HD 1; hp 5 each; #AT 1; D 1-6" } },
          fixed: [{ creature: "monster:skeleton", count: 4, notes: "THAC0 19" }],
        },
      ],
      pregens: [
        {
          id: "ned",
          name: "Ned Shakeshaft",
          audience: "player",
          race: "human",
          class: "thief",
          level: 3,
          alignment: "CN",
          gear: ["short sword", "thieves' picks"],
          stats: { adnd2e: { ability_scores: { str: 11, dex: 17, con: 12, int: 13, wis: 9, cha: 14 }, hp_max: 12 } },
        },
      ],
    },
    attachments: [
      { id: "cover", type: "image/png", sha256: "aa", size: 79, description: "The crypt door", audience: "player" },
      { id: "plan", type: "application/pdf", sha256: "bb", size: 99, description: "The original PDF", audience: "gm" },
      { id: "ritualist", type: "image/png", sha256: "cc", size: 79, description: "Cult ritualist token", audience: "gm" },
    ],
    keys: [],
    links: [],
    warnings: [],
  };
}

const SVG =
  '<svg xmlns="http://www.w3.org/2000/svg"><path class="floor" data-number="1" data-room="entry" ' +
  'data-label="Entry Hall" data-description="A cold hall." data-dm-notes="SECRET door north."/></svg>';
const PARSED = {
  map: { name: "crypt", description: "The crypt under the chapel.", dm_notes: null },
  feature_defs: {},
  rooms: { entry: { name: "entry", features: [] } },
  layers: [],
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  routes = {
    [`GET /api/modules/${MODULE}`]: () => json(200, module),
    [`GET /api/modules/${MODULE}/source`]: () => json(200, source()),
    "POST /api/dsl/render": () => json(200, { svg: SVG }),
    "POST /api/dsl/parse": () => json(200, { map: PARSED }),
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderAt(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/modules/:moduleId", element: <ModuleDetail /> },
      { path: "/modules/:moduleId/print", element: <ModulePrint /> },
    ],
    { initialEntries: [entry] },
  );
  const { container } = render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { container, router };
}

function renderAtWithUnmount(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([{ path: "/modules/:moduleId/print", element: <ModulePrint /> }], {
    initialEntries: [entry],
  });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <RouterProvider router={router} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const parts = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLElement>("[data-part]")).map((el) => el.dataset.part);

describe("ModulePrint", () => {
  it("prints the title page, the texts, the played maps, the NPCs and encounters, then the images", async () => {
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByText("Cult ritualist token");
    await waitFor(() => expect(container.querySelector("[data-part=map] svg")).not.toBeNull());

    expect(parts(container)).toEqual(["title", "text", "text", "map", "npcs", "encounters", "pregens", "images"]);

    const title = container.querySelector<HTMLElement>("[data-part=title]")!;
    expect(title.querySelector("h1")!.textContent).toBe("The Crypt of Saint Vellis");
    expect(title.textContent).toContain("Mara Quill");
    expect(title.textContent).toContain("Ot Venn");
    expect(title.textContent).toContain("1–3");
    expect(title.textContent).toContain("4");
    expect(title.textContent).toContain("The Vale");
    expect(title.querySelector("img")!.getAttribute("src")).toBe(`/api/modules/${MODULE}/assets/cover`);

    const texts = container.querySelectorAll<HTMLElement>("[data-part=text]");
    expect(texts[0].querySelector("h2")!.textContent).toContain("Introduction");
    expect(texts[1].querySelector("h2")!.textContent).toContain("Keyed encounters");

    // Each played map as MapPrint prints it: the DM view and its key. A library isn't a map to print.
    const map = container.querySelector<HTMLElement>("[data-part=map]")!;
    expect(map.textContent).toContain("crypt");
    expect(map.textContent).toContain("The crypt under the chapel.");
    expect(map.textContent).toContain("Room key");
    expect(map.textContent).toContain("Entry Hall");
    expect(map.textContent).toContain("SECRET door north.");
    expect(container.querySelectorAll("[data-part=map]")).toHaveLength(1);

    const npcs = container.querySelector<HTMLElement>("[data-part=npcs]")!;
    expect(npcs.textContent).toContain("Brother Ansel");
    expect(npcs.textContent).toContain("The last monk.");
    expect(npcs.textContent).toContain("Priest");
    const encounters = container.querySelector<HTMLElement>("[data-part=encounters]")!;
    expect(encounters.textContent).toContain("Skeleton guard");
    expect(encounters.textContent).toContain("skeleton");
    // The stat lines as printed, each under its name (faithful modules Task 15).
    const npcLine = npcs.querySelector("h3 + p")!;
    expect(npcLine.textContent).toBe("AC 5; MV 12; P3; hp 14; #AT 1; D 1-6");
    expect(encounters.querySelector("h3 + p")!.textContent).toBe("AC 7; MV 12; HD 1; hp 5 each; #AT 1; D 1-6");
    expect(encounters.textContent).toContain("4 × skeleton — THAC0 19");

    // The pregens as a table, one row each.
    const pregens = container.querySelector<HTMLElement>("[data-part=pregens]")!;
    expect(pregens.querySelector("h2")!.textContent).toBe("Pregenerated characters");
    const rows = Array.from(pregens.querySelectorAll("tr")).map((tr) =>
      Array.from(tr.querySelectorAll("th, td")).map((cell) => cell.textContent),
    );
    expect(rows).toEqual([
      ["Name", "Race", "Class", "Level", "Alignment", "Str", "Dex", "Con", "Int", "Wis", "Cha", "HP", "Gear"],
      ["Ned ShakeshaftPlayers", "human", "thief", "3", "CN", "11", "17", "12", "13", "9", "14", "12", "short sword, thieves' picks"],
    ]);

    // Only the image attachments, each with its description; the PDF isn't an image.
    const images = container.querySelector<HTMLElement>("[data-part=images]")!;
    expect(Array.from(images.querySelectorAll("figcaption")).map((c) => c.textContent)).toEqual([
      "The crypt doorPlayers",
      "Cult ritualist token",
    ]);
    expect(images.textContent).not.toContain("The original PDF");
  });

  it("includes a DM-only text, rendered as the editor shows it with read-aloud boxed", async () => {
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByText("Keyed encounters");
    const text = container.querySelectorAll<HTMLElement>("[data-part=text]")[1];
    expect(text.querySelector(":scope > h2")!.textContent).toContain("Keyed encounters");
    expect(text.querySelector(".text-page h2")!.textContent).toBe("C1. Entry Hall");
    const quotes = Array.from(text.querySelectorAll("blockquote"));
    // Under a keyed heading every quote is read-aloud; under another heading only the leading ones (Task 11).
    expect(quotes.map((q) => q.classList.contains("read-aloud"))).toEqual([true, true, true, false]);
    expect(quotes[0].textContent).toBe("Dust lies thick on the stairs.");
    // A ref shows as its entity's name, as in the editor.
    expect(text.querySelector(".ref-chip")!.textContent).toBe("Brother Ansel");
  });

  it("names a text once when its Markdown begins with its title as a heading", async () => {
    routes[`GET /api/modules/${MODULE}/source`] = () =>
      json(200, {
        ...source(),
        texts: [
          { id: "shrine", title: "The Sunken  Shrine", audience: "gm", map: null, markdown: "\n# the sunken shrine {#shrine}\n\nUnder the pond.\n" },
          { id: "intro", title: "Introduction", audience: "player", map: null, markdown: "# The Crypt\n\nIntro text.\n" },
        ],
      });
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByText("Under the pond.");
    const [shrine, intro] = Array.from(container.querySelectorAll<HTMLElement>("[data-part=text]"));
    // The text's own heading names it; the part heading would say it twice.
    expect(shrine.querySelector(":scope > h2")).toBeNull();
    expect(Array.from(shrine.querySelectorAll("h1, h2")).map((h) => h.textContent)).toEqual(["the sunken shrine"]);
    // A text whose heading is another title keeps its part heading.
    expect(intro.querySelector(":scope > h2")!.textContent).toBe("IntroductionPlayers");
  });

  it("texts flow, and only player items are tagged", async () => {
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByText("Cult ritualist token");
    const part = (name: string) => container.querySelector<HTMLElement>(`[data-part=${name}]`)!;
    const texts = Array.from(container.querySelectorAll<HTMLElement>("[data-part=text]"));
    // A text runs on after the one before it; a map and each section after the texts start a page.
    expect(styles.pageBreak).toBeTruthy();
    for (const text of texts) expect(text.classList.contains(styles.pageBreak)).toBe(false);
    for (const name of ["map", "npcs", "encounters", "pregens", "images"]) {
      expect(part(name).classList.contains(styles.pageBreak)).toBe(true);
    }
    // One note says what is DM material; only what players may see carries a tag.
    expect(part("title").textContent).toContain("Everything here is DM material unless it is marked Players.");
    expect(texts[0].querySelector(":scope > h2")!.textContent).toBe("IntroductionPlayers");
    expect(texts[1].querySelector(":scope > h2")!.textContent).toBe("Keyed encounters");
    expect(container.textContent).not.toContain("DM only");
    expect(part("npcs").querySelector("h3")!.textContent).toBe("Brother Ansel");
  });

  it("tags the players' images, and only those", async () => {
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByText("Cult ritualist token");
    const figures = Array.from(container.querySelectorAll<HTMLElement>("[data-part=images] figure"));
    // The crypt door is a player image; the ritualist token is the DM's.
    expect(figures.map((f) => f.querySelector("figcaption")!.textContent)).toEqual([
      "The crypt doorPlayers",
      "Cult ritualist token",
    ]);
  });

  it("a text titled as the module isn't a second title", async () => {
    routes[`GET /api/modules/${MODULE}/source`] = () =>
      json(200, {
        ...source(),
        texts: [
          { id: "front", title: "The Crypt of  Saint Vellis", audience: "gm", map: null, markdown: "Front matter.\n" },
          ...source().texts,
        ],
      });
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByText("Front matter.");
    const front = container.querySelector<HTMLElement>("[data-part=text]")!;
    expect(front.querySelector("h1, h2")).toBeNull();
    const titles = Array.from(container.querySelectorAll("h1, h2")).filter((h) => h.textContent?.includes("Saint Vellis"));
    expect(titles.map((h) => h.tagName)).toEqual(["H1"]);
  });

  it("the map key numbers each room once", async () => {
    const key = async (svg: string) => {
      routes["POST /api/dsl/render"] = () => json(200, { svg });
      const { container, unmount } = renderAtWithUnmount(`/modules/${MODULE}/print`);
      await waitFor(() => expect(container.querySelector("[data-part=map] li h3")).not.toBeNull());
      const headings = Array.from(container.querySelectorAll("[data-part=map] li h3")).map((h) => h.textContent);
      unmount();
      return headings;
    };
    const floor = (attrs: string) =>
      `<svg xmlns="http://www.w3.org/2000/svg"><path class="floor" data-room="caravan" ${attrs}/></svg>`;
    // Numbers off: the book's label carries its own number, and the renderer's isn't added.
    expect(await key(floor('data-number="1" data-numbered="false" data-label="4. The Destroyed Caravan"'))).toEqual([
      "4. The Destroyed Caravan",
    ]);
    // Numbers on, a label that already starts with the room's number: still once.
    expect(await key(floor('data-number="4" data-label="4. The Destroyed Caravan"'))).toEqual(["4. The Destroyed Caravan"]);
    // Numbers on, a book map whose labels carry their own keys: the renderer's number isn't added either.
    expect(await key(floor('data-number="1" data-label="4. The Destroyed Caravan"'))).toEqual(["4. The Destroyed Caravan"]);
    expect(await key(floor('data-number="1" data-label="C7. Vestry"'))).toEqual(["C7. Vestry"]);
    // Numbers on and a plain label: the renderer's number.
    expect(await key(floor('data-number="1" data-label="Hall"'))).toEqual(["1. Hall"]);
  });

  it("prints an empty module as its title page only", async () => {
    routes[`GET /api/modules/${MODULE}`] = () => json(200, { ...module, metadata: {}, maps: [] });
    routes[`GET /api/modules/${MODULE}/source`] = () =>
      json(200, { texts: [], entities: {}, attachments: [], keys: [], links: [], warnings: [] });
    const { container } = renderAt(`/modules/${MODULE}/print`);
    await waitFor(() => expect(container.querySelector("[data-part=title] h1")).not.toBeNull());
    await waitFor(() => expect(fetchMock.mock.calls.some(([p]) => p === `/api/modules/${MODULE}/source`)).toBe(true));
    await screen.findByText("The Crypt of Saint Vellis");
    expect(parts(container)).toEqual(["title"]);
    expect(fetchMock.mock.calls.some(([p]) => String(p).startsWith("/api/dsl/"))).toBe(false);
  });

  it("is opened from the module page's Print button", async () => {
    renderAt(`/modules/${MODULE}`);
    const link = await screen.findByRole("link", { name: "Print the module" });
    expect(link.getAttribute("href")).toBe(`/modules/${MODULE}/print`);
  });

  it("never follows the look, and gives it back when it closes", async () => {
    document.documentElement.dataset.look = "dark-dungeon";
    const { router } = renderAt(`/modules/${MODULE}/print`);
    await screen.findByRole("button", { name: "Print or save as PDF" });
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
    await act(() => router.navigate(`/modules/${MODULE}`));
    expect(document.documentElement.dataset.look).toBe("dark-dungeon");
    delete document.documentElement.dataset.look;
  });

  it("prints a map without the look", async () => {
    document.documentElement.dataset.look = "gold-wood";
    routes[`GET /api/modules/${MODULE}/maps/crypt`] = () => json(200, { name: "crypt", source: "map crypt" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const router = createMemoryRouter([{ path: "/maps/:moduleId/:mapName/print", element: <MapPrint /> }], {
      initialEntries: [`/maps/${MODULE}/crypt/print`],
    });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <RouterProvider router={router} />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(document.documentElement.hasAttribute("data-look")).toBe(false);
    delete document.documentElement.dataset.look;
  });
});
