// Plateau 7's maps in a real browser (plan 7 Task 21), against `delve serve` with a fake `claude`
// (tests/e2e/fake_play_server.py), whose vision calls read the synthetic picture's truth and whose drawings from a
// description are the warren's and the shrine's maps:
// - a player's seat sees the region map under its fog, on a laptop and on a phone: the party, the places the party
//   knows, and never a hidden place, a place in land it doesn't know, or a planted secret;
// - the organiser imports a picture with its key (1 hex = 30 miles) into the crypt module and opens its review;
// - the world-map editor on the campaign's region map;
// - two dungeon-map drafts from a description, side by side, before either is kept.
// Screenshots in e2e/screenshots/.
//
// It runs after world.spec.ts (file order), on the crypt's campaign, whose party stands in the Free City of Greyhawk.
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const python = process.env.DELVE_E2E_PYTHON ?? "uv run python";
const SECRET = "SECRET-XYZZY";
// The region map's places tagged hidden, those the party doesn't know from the Free City, and the planted one: never
// on the seat's map nor in its known places (the quest's title names Hardby), and the secret nowhere on the page.
const UNSEEN = ["Clan Temple", "Ambush Site", "Hardby", "Tellach", SECRET];

type Feature = { id: string; type: "Feature"; geometry: { type: string; coordinates: unknown }; properties: Record<string, unknown> };

async function noneOf(page: Page, names: string[]) {
  const map = page.getByRole("region", { name: /^The world map: / });
  const places = page.getByRole("list", { name: "Known places" });
  for (const name of names) {
    await expect(map).not.toContainText(name);
    if (await places.count()) await expect(places).not.toContainText(name);
  }
  await expect(page.locator("body")).not.toContainText(SECRET);
}

test("a seat's fogged world map, a picture's import and review, the editor and the map drafts", async ({
  page,
  browser,
  request,
}, testInfo) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  const path = `/api/campaigns/${campaign.id}`;
  const json = { headers: { "Content-Type": "application/json" } };

  // A secret place planted by the organiser beside Tellach, in land the party doesn't know.
  const region = await (await request.get(`${path}/world-maps/greyhawk-region`)).json();
  const tellach = (region.geo.features as Feature[]).find((f) => f.properties.name === "Tellach")!;
  const planted: Feature = {
    ...tellach,
    id: "secret-tower",
    properties: { ...tellach.properties, name: `${SECRET} Tower`, kind: "ruin", description: SECRET },
  };
  const saved = await request.put(`${path}/world-maps/greyhawk-region`, {
    ...json,
    data: { title: region.title, geo: { ...region.geo, features: [...region.geo.features, planted] } },
  });
  expect(saved.ok(), await saved.text()).toBe(true);

  // Bo joins as a player in a browser of his own, with an account (the API's join logs that browser in).
  const { join_token: token } = await (await request.get(`${path}/invite`)).json();
  const bo = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const joined = await bo.request.post(`/api/join/${token}/account`, {
    ...json,
    data: { username: "bo.world", password: "correct horse battery", display_name: "Bo", language: "en", role: "player" },
  });
  expect(joined.status()).toBe(201);
  const seat = await bo.newPage();

  // His view and tiles from the routes: the party's land only.
  const view = await (await seat.request.get(`${path}/world-maps/greyhawk-region/view`)).json();
  expect(view.known.all).toBe(false);
  const names = (view.features as { name: string }[]).map((f) => f.name);
  expect(names).toContain("Greyhawk");
  for (const name of UNSEEN) expect(JSON.stringify(view)).not.toContain(name);
  expect((await seat.request.get(`${path}/world-maps/greyhawk-region/dm-view`)).status()).toBe(403);

  // The play screen at 1280x800: the World tab, the map under its fog, the party and the known places.
  await seat.goto(`/play/${campaign.id}`);
  const aside = seat.getByTestId("play-aside");
  await aside.getByRole("tab", { name: "Maps" }).click();
  await aside.getByRole("tab", { name: "World" }).click();
  const world = aside.getByTestId("world-panel");
  const map = world.getByRole("region", { name: /^The world map: / });
  await expect(map).toBeVisible();
  await expect(map.getByRole("img", { name: "The party" })).toBeVisible();
  await expect(world.getByRole("list", { name: "Known places" })).toContainText("Greyhawk");
  await noneOf(seat, UNSEEN);
  await world.scrollIntoViewIfNeeded();
  await seat.screenshot({ path: "e2e/screenshots/worldmap-seat-1280x800.png" });

  // A phone: the map fills the World screen, the known places in a sheet over its foot.
  await seat.setViewportSize({ width: 390, height: 844 });
  await seat.getByTestId("tab-world").click();
  const screen = seat.getByTestId("phone-screen");
  await expect(screen).toHaveAttribute("aria-label", "World");
  await expect(screen.getByRole("region", { name: /^The world map: / })).toBeVisible();
  await expect(screen.getByRole("img", { name: "The party" })).toBeVisible();
  await screen.getByRole("button", { name: "Known places" }).click();
  await expect(screen.getByRole("list", { name: "Known places" })).toContainText("Greyhawk");
  await noneOf(seat, UNSEEN);
  expect(await seat.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await seat.screenshot({ path: "e2e/screenshots/worldmap-seat-phone-390x844.png" });
  await bo.close();

  // The organiser imports a picture of a map with its key into the crypt module: 1 hex = 30 miles.
  const picture = testInfo.outputPath("westmarch.png");
  execSync(`${python} -m tests.e2e.fake_play_server --picture "${picture}"`, { cwd: ".." });
  const modules: { id: string; title: string }[] = await (await request.get("/api/modules")).json();
  const crypt = modules.find((m) => m.title === "The Crypt of Saint Vellis")!;
  await page.goto(`/modules/${crypt.id}`);
  await page.getByRole("tab", { name: "Maps" }).click();
  await page.getByRole("button", { name: "Import a world map" }).click();
  const dialog = page.getByRole("dialog", { name: "Import a world map" });
  await dialog.getByLabel("A picture with its key").check();
  await dialog.getByLabel("Name", { exact: true }).fill("westmarch");
  await dialog.getByLabel("Title").fill("The Westmarch");
  await dialog.getByLabel("The picture").setInputFiles({
    name: "westmarch.png",
    mimeType: "image/png",
    buffer: readFileSync(picture),
  });
  await dialog.getByLabel("Grid").selectOption("hex");
  await dialog.getByLabel("Distance").fill("30");
  await dialog.getByLabel("Units").selectOption("miles");
  await dialog.getByRole("button", { name: "Start reading" }).click();
  await dialog.getByRole("link", { name: "Review the map" }).click({ timeout: 60_000 });

  // The review: the doubts first, then the colours with Claude's suggestions, beside the map over its picture.
  await expect(page.getByRole("heading", { name: "Review: The Westmarch" })).toBeVisible();
  await expect(page.getByText("Doubtful readings")).toBeVisible();
  await expect(page.getByText("Suggested: forest").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Accept the map" })).toBeVisible();
  await expect(page.locator(".leaflet-tile-loaded").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/worldmap-review-1280x800.png" });

  // The world-map editor on the campaign's region map: the planted place is the organiser's to see.
  await page.goto(`/world-maps/campaign/${campaign.id}/greyhawk-region`);
  await expect(page.getByRole("toolbar", { name: /./ })).toBeVisible();
  await expect(page.getByRole("region", { name: /^The world map: / })).toBeVisible();
  await expect(page.locator("body")).toContainText(`${SECRET} Tower`);
  await page.screenshot({ path: "e2e/screenshots/worldmap-editor-1280x800.png" });

  // Two dungeon-map drafts from a description, side by side; nothing is in the module until one is kept.
  await page.goto(`/modules/${crypt.id}`);
  await page.getByRole("tab", { name: "Maps" }).click();
  await page.getByRole("button", { name: "Generate a map" }).click();
  const drafts = page.getByRole("dialog", { name: "Generate a map" });
  for (const [description, name] of [
    ["A kobold warren: a burrow mouth, a den, and the chief's hole behind it.", "warren"],
    ["A sunken shrine: a flooded stair down to a drowned chapel.", "shrine"],
  ]) {
    await drafts.getByLabel("Description").fill(description);
    await drafts.getByLabel("Name of the map (optional)").fill(name);
    await drafts.getByRole("button", { name: "Draw it" }).click();
    await expect(drafts.getByText(name, { exact: true }).first()).toBeVisible({ timeout: 60_000 });
  }
  await expect(drafts.getByTestId("map-draft")).toHaveCount(2, { timeout: 60_000 });
  await drafts.getByRole("button", { name: "Close" }).click();
  // The Maps tab lists the drafts too, side by side, each drawn, with Keep and Discard.
  const listed = page.getByRole("region", { name: "Drafts" });
  await expect(listed.getByTestId("map-draft")).toHaveCount(2);
  await expect(listed.locator("svg").first()).toBeVisible();
  await listed.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e/screenshots/map-drafts-1280x800.png" });
  const maps: { name: string }[] = (await (await request.get(`/api/modules/${crypt.id}`)).json()).maps;
  expect(maps.map((m) => m.name)).not.toContain("warren");
});
