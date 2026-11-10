// Looks and banners in a real browser (looks and banners plan Task 8), against the same fake server as the other
// specs. Each look in Preferences, the choice set again before any app script after a reload, the play screen's
// header on one line in every look, the play screen and the map editor in Dark dungeon, and what each look fetches:
// only Delve's own origin, no font or texture in Delve today, Cinzel and the wood in Gold and wood. Then a new
// campaign's banner, painted by the free fake images (plan decision 7), on its empty story and on its module's page.
// Screenshots in e2e/screenshots/. It runs first by file order: it leaves Delve today set and no campaign of its own,
// so the later specs find the one crypt campaign and their screenshots stay Delve today's.
import { expect, test, type Browser, type Page } from "@playwright/test";

type Look = "delve" | "gold-wood" | "dark-dungeon";
const LOOKS: Look[] = ["delve", "gold-wood", "dark-dungeon"];
const json = { headers: { "Content-Type": "application/json" } };

/** Every URL the page asks for, from now on. */
function recordRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (request) => urls.push(request.url()));
  return urls;
}

const fonts = (urls: string[]) => urls.filter((url) => /\.woff2?(\?|$)/.test(url));
const textures = (urls: string[]) => urls.filter((url) => /\/looks\/textures\/|\/(wood|stone)-[^/]*\.jpg/.test(url));

/** A fresh page whose browser holds `look`, set before Delve's first script; its requests. */
async function freshPage(browser: Browser, baseURL: string, look: Look): Promise<{ page: Page; urls: string[] }> {
  const context = await browser.newContext({ baseURL, viewport: { width: 1280, height: 800 } });
  if (look !== "delve") await context.addInitScript((l) => localStorage.setItem("delve.look", l), look);
  const page = await context.newPage();
  return { page, urls: recordRequests(page) };
}

/** The page is drawn, with its fonts in: what a look fetches has been asked for. */
async function settled(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => document.fonts.ready);
}

test("switch looks, and the choice survives a reload", async ({ page, request, browser, baseURL }) => {
  const urls = recordRequests(page);
  const [campaign] = await (await request.get("/api/campaigns")).json();
  const picker = page.locator(".look-picker select");

  // Preferences, in each look.
  await page.goto("/preferences");
  await expect(picker).toHaveValue("delve");
  await settled(page);
  await page.screenshot({ path: "e2e/screenshots/look-delve-1280x800.png" });
  for (const look of ["gold-wood", "dark-dungeon"] as const) {
    await picker.selectOption(look);
    await expect(page.locator("html")).toHaveAttribute("data-look", look);
    await settled(page);
    await page.screenshot({ path: `e2e/screenshots/look-${look}-1280x800.png` });
  }

  // A reload: look.js sets the choice again before any of Delve's own scripts run (they run once the document is
  // parsed, after `interactive`), so nothing flashes.
  await page.addInitScript(() => {
    document.addEventListener("readystatechange", () => {
      if (document.readyState !== "interactive") return;
      const w = window as unknown as { lookAtParse: unknown };
      w.lookAtParse = { look: document.documentElement.dataset.look, app: document.getElementById("root")?.childElementCount };
    });
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(() => document.documentElement.dataset.look === "dark-dungeon");
  expect(await page.evaluate(() => (window as unknown as { lookAtParse: unknown }).lookAtParse)).toEqual({
    look: "dark-dungeon",
    app: 0,
  });

  // The play screen's header keeps one line at 1280 px in every look, chosen with its own picker.
  await page.goto(`/play/${campaign.id}`);
  const head = page.locator(".play-head");
  const headPicker = head.locator(".look-picker select");
  await expect(head.getByRole("button", { name: "Table options" })).toBeVisible();
  for (const look of LOOKS) {
    await headPicker.selectOption(look);
    await expect(headPicker).toHaveValue(look);
    await page.evaluate(() => document.fonts.ready);
    const [title, options] = [head.locator("h1"), head.locator(".table-options")];
    const [titleBox, optionsBox] = [await title.boundingBox(), await options.boundingBox()];
    expect(Math.abs(titleBox!.y + titleBox!.height / 2 - (optionsBox!.y + optionsBox!.height / 2)), look).toBeLessThan(
      titleBox!.height / 2,
    );
    expect((await head.boundingBox())!.height, look).toBeLessThan(60);
  }

  // The play screen and the map editor in Dark dungeon.
  await headPicker.selectOption("dark-dungeon");
  await expect(page.locator("html")).toHaveAttribute("data-look", "dark-dungeon");
  // The campaign has had no act yet: the tavern has the story's place, with the banner at its top (players and tavern).
  await expect(page.getByTestId("tavern").locator(".banner-story img")).toBeVisible();
  await settled(page);
  await page.screenshot({ path: "e2e/screenshots/look-dark-dungeon-play-1280x800.png" });
  await page.goto(`/maps/${encodeURIComponent(campaign.module_id)}/crypt`);
  await expect(page.locator(".monaco-editor").first()).toBeVisible();
  await expect(page.locator(".monaco-editor .view-lines")).toContainText("Crypt of Saint Vellis");
  await settled(page);
  await page.screenshot({ path: "e2e/screenshots/look-dark-dungeon-editor-1280x800.png" });

  // The map's preview draws as in Delve today: the same colours with the look as without it.
  const mapColours = () =>
    page.evaluate(() => {
      const host = document.querySelector("[class*='stageHost']")!;
      const svg = host.querySelector("[class*='mapLayer'] svg")!;
      const [h, s] = [getComputedStyle(host), getComputedStyle(svg)];
      return [h.backgroundColor, s.borderTopColor, s.boxShadow, h.getPropertyValue("--accent")];
    });
  await expect(page.locator("[class*='mapLayer'] svg").first()).toBeVisible();
  const withLook = await mapColours();
  await page.evaluate(() => document.documentElement.removeAttribute("data-look"));
  expect(withLook).toEqual(await mapColours());
  await page.evaluate(() => document.documentElement.setAttribute("data-look", "dark-dungeon"));

  // Everything fetched came from Delve itself (the map preview's `asset:` token art is no fetch).
  const origin = new URL(page.url()).origin;
  const outside = urls.filter((url) => /^(https?|wss?):/.test(url) && new URL(url).origin !== origin);
  expect(urls.filter((url) => url.startsWith("http")).length).toBeGreaterThan(10);
  expect(outside).toEqual([]);

  // Delve today fetches no font and no texture; Gold and wood its Cinzel and its wood.
  const today = await freshPage(browser, baseURL!, "delve");
  for (const path of ["/preferences", `/play/${campaign.id}`]) {
    await today.page.goto(path);
    await settled(today.page);
  }
  expect(await today.page.evaluate(() => document.documentElement.hasAttribute("data-look"))).toBe(false);
  expect(fonts(today.urls)).toEqual([]);
  expect(textures(today.urls)).toEqual([]);
  await today.page.context().close();

  const gold = await freshPage(browser, baseURL!, "gold-wood");
  await gold.page.goto(`/play/${campaign.id}`);
  await settled(gold.page);
  expect(fonts(gold.urls).some((url) => /cinzel/i.test(url)), fonts(gold.urls).join("\n")).toBe(true);
  expect(textures(gold.urls).some((url) => /wood/i.test(url)), gold.urls.join("\n")).toBe(true);
  await gold.page.context().close();

  // Delve today again, so the later specs' screenshots stay as they were.
  await page.goto("/preferences");
  await picker.selectOption("delve");
  await expect(page.locator("html")).not.toHaveAttribute("data-look", /.*/);
  expect(await page.evaluate(() => localStorage.getItem("delve.look"))).toBe("delve");
});

test("a new campaign's banner shows on its empty story and on its module", async ({ page, request }) => {
  const [crypt] = await (await request.get("/api/campaigns")).json();
  const made = await request.post("/api/campaigns", {
    ...json,
    data: { name: "The Bell Tower", module_id: crypt.module_id },
  });
  expect(made.status(), await made.text()).toBe(201);
  const campaign: string = (await made.json()).id;
  try {
    // Asked for when it was made, and painted at once by the free fake images.
    await expect
      .poll(async () => (await (await request.get(`/api/campaigns/${campaign}`)).json()).banner?.image_id ?? null)
      .not.toBeNull();

    // Its play screen opens on it: the tavern's top before the first act, then the empty story's.
    await page.goto(`/play/${campaign}`);
    const banner = page.getByTestId("tavern").locator(".banner-story img");
    await expect(banner).toBeVisible();
    await expect.poll(() => banner.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0);
    await page.getByTestId("tavern-back").click();
    const onStory = page.getByTestId("story").locator(".banner-story img");
    await expect(onStory).toBeVisible();
    await expect.poll(() => onStory.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0);
    await page.screenshot({ path: "e2e/screenshots/banner-campaign-1280x800.png" });

    // The module's page shows it as a thumbnail that opens the campaign.
    await page.goto(`/modules/${crypt.module_id}`);
    const thumb = page.locator(`.banner-thumbs a[href="/campaigns/${campaign}"]`);
    await expect(thumb).toBeVisible();
    await expect(thumb).toContainText("The Bell Tower");
    await expect.poll(() => thumb.locator("img").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
    await page.screenshot({ path: "e2e/screenshots/banner-module-1280x800.png" });
  } finally {
    expect((await request.delete(`/api/campaigns/${campaign}`, json)).status()).toBe(204);
  }
  expect(await (await request.get("/api/campaigns")).json()).toHaveLength(1);
});
