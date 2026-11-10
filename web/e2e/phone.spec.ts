// The organiser's screens on a phone (walkthrough-fixes Task 7, E9): Modules, a module in each of its tabs, the map
// editor in both its views, House rules with a rule picked, the module and map print, and a character sheet, at
// 390x844. None of them may scroll sideways (Review Focus 5). Screenshots in e2e/screenshots/.
//
// It changes nothing: the play screen's spec, which runs after it, still finds the crypt's campaign alone.
import { expect, test, type Page } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

const TABS = ["Text", "NPCs", "Encounters", "Factions", "Quests", "Attachments", "Maps", "Details"];

async function fitsTheWidth(page: Page, screen: string) {
  // Let the layout settle (fonts, the drawing) before measuring.
  await page.waitForTimeout(300);
  const { width, wide } = await page.evaluate(() => {
    // The outermost elements that run past the screen's edge, to name in the failure.
    const wide: string[] = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      if (el.getBoundingClientRect().right > 391 && el.parentElement!.getBoundingClientRect().right <= 391)
        wide.push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ").join(".")}`);
    }
    return { width: document.documentElement.scrollWidth, wide: wide.slice(0, 8) };
  });
  // Soft, so one run names every screen that is too wide.
  expect.soft(width, `${screen} is ${width} px wide: ${wide.join(", ")}`).toBeLessThanOrEqual(390);
}

async function shoot(page: Page, name: string) {
  await page.screenshot({ path: `e2e/screenshots/${name}-390x844.png` });
}

test("the module editor, map editor, house rules and print fit a phone", async ({ page, request }) => {
  const modules: { id: string; title: string }[] = await (await request.get("/api/modules")).json();
  const crypt = modules.find((m) => m.title === "The Crypt of Saint Vellis")!;
  const detail: { maps: { name: string }[] } = await (await request.get(`/api/modules/${crypt.id}`)).json();
  const mapName = detail.maps[0].name;

  await page.goto("/modules");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("The Crypt of Saint Vellis").first()).toBeVisible();
  await fitsTheWidth(page, "Modules");
  await shoot(page, "phone-modules");

  await page.goto(`/modules/${crypt.id}`);
  for (const name of TABS) {
    await page.getByRole("tab", { name, exact: true }).click();
    await expect(page.getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
    if (name === "Text") await page.getByRole("button", { name: /Keyed encounters/ }).click();
    if (name === "NPCs") await page.getByRole("button", { name: /Brother Kael/ }).click();
    await fitsTheWidth(page, `The module's ${name} tab`);
    await shoot(page, `phone-module-${name.toLowerCase()}`);
  }

  // The map editor: the code and the drawing are two tabs, not side by side.
  await page.goto(`/maps/${crypt.id}/${encodeURIComponent(mapName)}`);
  const code = page.getByRole("tab", { name: "Code" });
  const drawing = page.getByRole("tab", { name: "Drawing" });
  await expect(code).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".monaco-editor").first()).toBeVisible();
  await fitsTheWidth(page, "The map editor's code");
  await shoot(page, "phone-map-editor-code");
  await drawing.click();
  await expect(drawing).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".monaco-editor").first()).toBeHidden();
  await expect(page.getByLabel("Zoom in")).toBeVisible();
  await fitsTheWidth(page, "The map editor's drawing");
  await shoot(page, "phone-map-editor-drawing");

  // House rules: the library, then a rule as its own view with a link back.
  await page.goto("/house-rules");
  await expect(page.getByRole("heading", { level: 2, name: "Rules" })).toBeVisible();
  await fitsTheWidth(page, "House rules");
  await shoot(page, "phone-house-rules");
  await page.locator(".rule-pick").last().click();
  const back = page.getByRole("button", { name: "All house rules" });
  await expect(back).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Rules" })).toBeHidden();
  await fitsTheWidth(page, "A house rule");
  await shoot(page, "phone-house-rule");
  await back.click();
  await expect(page.getByRole("heading", { level: 2, name: "Rules" })).toBeVisible();

  // The print views fit the width.
  await page.goto(`/modules/${crypt.id}/print`);
  await expect(page.locator('[data-part="title"]')).toBeVisible();
  await fitsTheWidth(page, "The module in print");
  await shoot(page, "phone-module-print");
  // The module New module converted, when its spec ran first (as in `make e2e-browser`): a book's text and its map.
  const shrine = modules.find((m) => m.title === "The Sunken Shrine");
  if (shrine) {
    await page.goto(`/modules/${shrine.id}/print`);
    await expect(page.locator('[data-part="map"] svg').first()).toBeVisible();
    await fitsTheWidth(page, "The converted module in print");
    await shoot(page, "phone-converted-print");
  }
  await page.goto(`/maps/${crypt.id}/${encodeURIComponent(mapName)}/print`);
  await expect(page.locator("svg").first()).toBeVisible();
  await fitsTheWidth(page, "The map in print");
  await shoot(page, "phone-map-print");
});

// The tab bar holds the first four areas and More (DEL-188): More opens every area, Help and the language (DEL-292) in
// a sheet, so nothing is cut at the screen's edge and the page never scrolls sideways.
test("every area is reachable from the phone's tab bar", async ({ page }) => {
  await page.goto("/campaigns");
  const bar = page.getByRole("navigation", { name: "Areas" });
  const visible = async () => (await bar.getByRole("link").filter({ visible: true }).allTextContents()).map((l) => l.trim());
  await expect(bar.getByRole("link", { name: "Play", exact: true })).toBeVisible();
  expect(await visible()).toEqual(["Play", "Campaigns", "Modules", "Maps"]);
  await fitsTheWidth(page, "The tab bar");
  await shoot(page, "phone-tab-bar");
  await page.getByTestId("nav-more").click();
  await expect(bar.getByRole("link", { name: "Preferences", exact: true })).toBeVisible();
  const labels = await visible();
  expect(labels).toEqual(["Play", "Campaigns", "Modules", "Maps", "House rules", "Rulesets", "Settings", "Board", "Preferences"]);
  for (const label of labels) {
    const box = (await bar.getByRole("link", { name: label, exact: true }).boundingBox())!;
    expect.soft(box.x, `${label} starts off the screen`).toBeGreaterThanOrEqual(0);
    expect.soft(box.x + box.width, `${label} ends off the screen`).toBeLessThanOrEqual(391);
    expect.soft(box.y, `${label} is above the screen`).toBeGreaterThanOrEqual(0);
    expect.soft(box.y + box.height, `${label} is below the screen`).toBeLessThanOrEqual(845);
  }
  await expect(bar.getByRole("button", { name: "Help" })).toBeVisible();
  await expect(bar.getByRole("combobox", { name: "Language" })).toBeVisible();
  await fitsTheWidth(page, "The nav's sheet");
  await shoot(page, "phone-tab-bar-more");
  await bar.getByRole("link", { name: "Preferences", exact: true }).click();
  await expect(page).toHaveURL(/\/preferences$/);
  await expect(page.getByRole("heading", { level: 1, name: "Preferences" })).toBeVisible();
  await expect(bar.getByRole("link", { name: "Preferences", exact: true })).toBeHidden(); // the sheet closed
});

// The sheet's stats on a phone (walkthrough P5): every number on one line, with the reader's separators. The sheets
// are the server's with bigger numbers, rewritten in the browser only, so the server's campaign stays as it is.
test("a character sheet fits a phone, each stat on one line", async ({ page, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  await page.route(`**/api/campaigns/${campaign.id}/dm/characters`, async (route) => {
    const characters = await (await route.fetch()).json();
    for (const character of characters) {
      Object.assign(character.sheet, { hp_max: 62, ac: -2, thac0: 11, movement_rate: 12 });
      Object.assign(character.state, { hp: 61, xp: 1234567 });
    }
    await route.fulfill({ json: characters });
  });

  await page.goto(`/campaigns/${campaign.id}?tab=party`);
  const stats = page.locator(".sheet-stats").first();
  await expect(stats).toContainText("61 / 62");
  await expect(stats).toContainText("1,234,567");
  await stats.scrollIntoViewIfNeeded();
  await fitsTheWidth(page, "The campaign's sheets");
  for (const dd of await stats.locator("dd").all()) {
    const height = (await dd.boundingBox())!.height;
    const line = await dd.evaluate((el) => parseFloat(getComputedStyle(el).lineHeight));
    expect.soft(height, `"${await dd.textContent()}" takes more than one line`).toBeLessThan(2 * line);
  }
  await stats.locator("xpath=ancestor::article[1]").screenshot({ path: "e2e/screenshots/sheet-390.png" });
});
