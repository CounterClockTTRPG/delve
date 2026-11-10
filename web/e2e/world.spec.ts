// The world in a real browser (plan 6 Task 12, plan 7 Task 21), against `delve serve` with a fake `claude`: the World
// panel beside the map with the region map in Leaflet (the party's marker and the known places listed), a known
// quest, a known faction's standing and a horse; the same on a phone as the fourth screen; the portraits on the party
// sidebar; and the campaign page's world-map list. A planted secret in the DM-only fields never shows on the play
// screen, nor do the region map's hidden places. Screenshots in e2e/screenshots/.
//
// It runs after the play screen's and the table's specs, so the party (Garrek and Pippa, with portraitgen portraits)
// exists and stands in the Free City of Greyhawk (tests/e2e/fake_play_server.py).
import { expect, test } from "@playwright/test";

const SECRET = "SECRET-XYZZY";
// The region map's places tagged hidden, and those the party doesn't know yet from the Free City. (The quest names
// Hardby: they are looked for on the map and in its known places.)
const UNKNOWN = ["Clan Temple", "Ambush Site", "Hardby", "Tellach"];

test("the World panel, the portraits, the phone's World screen and the world-map list", async ({ page, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  const path = `/api/campaigns/${campaign.id}`;
  const characters: { id: string; name: string }[] = await (await request.get(`${path}/characters`)).json();
  const garrek = characters.find((c) => c.name === "Garrek")!;

  // The organiser's routes: a known quest with a note the characters don't know, a known faction and an unknown one,
  // and Garrek's horse with the DM's notes.
  const json = { headers: { "Content-Type": "application/json" } };
  const put = async (rest: string, data: unknown) =>
    expect((await request.put(`${path}/${rest}`, { ...json, data })).ok()).toBe(true);
  await put("quests/letter-to-hardby", {
    title: "Carry the letter to Hardby",
    status: "active",
    known: true,
    giver: "Dard Lorne",
    stakes: "The Despotrix must have it before the new moon.",
    log: [
      { day: 1, text: "Dard Lorne gave you a sealed letter at dawn.", known: true },
      { day: 1, text: `${SECRET}: the letter is forged.`, known: false },
    ],
    notes_md: `${SECRET}: Lorne works for the Scarlet Brotherhood.`,
  });
  await put("quests/the-brotherhood", { title: `${SECRET} plot`, known: false });
  await put("factions/hardby-court", { name: "The Despotrix's court", known: true, reputation: 25, notes_md: SECRET });
  await put("factions/scarlet", { name: `${SECRET} Brotherhood`, known: false });
  const horse = await request.post(`${path}/possessions`, {
    ...json,
    data: { name: "Bess", kind: "mount", species: "riding horse", owner: garrek.id, notes_md: `${SECRET}: stolen.` },
  });
  expect(horse.status()).toBe(201);

  // The play screen at 1280x800: the World tab beside the map.
  await page.goto(`/play/${campaign.id}`);
  await expect(page.getByRole("heading", { name: "The Crypt of Saint Vellis" })).toBeVisible();
  await expect(page.locator(".play-head .row-meta")).toContainText("Planting 576 CY");

  // The portraits on the party sidebar, drawn by portraitgen in the browser.
  const party = page.getByRole("region", { name: "Party" });
  await expect(party.getByRole("img", { name: "Garrek" })).toBeVisible();
  await expect(party.getByRole("img", { name: "Pippa" })).toBeVisible();
  await expect(party.locator("svg").first()).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/party-portraits-1280x800.png" });

  const aside = page.getByTestId("play-aside");
  await aside.getByRole("tab", { name: "Maps" }).click();
  await aside.getByRole("tab", { name: "World" }).click();
  const world = aside.getByTestId("world-panel");
  await expect(world).toContainText("Carry the letter to Hardby");
  await expect(world).toContainText("Dard Lorne gave you a sealed letter at dawn.");
  await expect(world).toContainText("The Despotrix's court");
  await expect(world).toContainText("Friendly");
  await expect(world).toContainText("Bess");
  await expect(world).toContainText("The party is at Greyhawk.");
  const map = world.getByRole("region", { name: /^The world map: / });
  await expect(map).toBeVisible();
  await expect(map.getByRole("img", { name: "The party" })).toBeVisible();
  await expect(map.locator("canvas").first()).toBeAttached(); // the known cells' terrain
  const places = world.getByRole("list", { name: "Known places" });
  await expect(places).toContainText("Greyhawk");
  await expect(places).toContainText("You are here");
  await expect(map.locator(".world-scale")).toHaveText(/^\d+ mi$/);
  for (const name of UNKNOWN) {
    await expect(map).not.toContainText(name);
    await expect(places).not.toContainText(name);
  }
  await expect(page.locator("body")).not.toContainText(SECRET);
  await world.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/world-panel-1280x800.png" });

  // A phone: World is the bottom bar's fourth screen.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId("tab-world").click();
  const screen = page.getByTestId("phone-screen");
  await expect(screen).toHaveAttribute("aria-label", "World");
  await expect(screen).toContainText("Carry the letter to Hardby");
  await expect(screen.getByRole("region", { name: /^The world map: / })).toBeVisible();
  await expect(screen.getByRole("img", { name: "The party" })).toBeVisible();
  for (const name of UNKNOWN) await expect(screen.getByRole("region", { name: /^The world map: / })).not.toContainText(name);
  await expect(page.locator("body")).not.toContainText(SECRET);
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "e2e/screenshots/world-phone-390x844.png" });

  // The campaign page: the world maps the campaign copied, each with Edit and Start knowledge; Import above them.
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(`/campaigns/${campaign.id}?tab=maps`);
  const heading = page.getByRole("heading", { name: "World maps" });
  await expect(heading).toBeVisible();
  const row = page.locator(".world-maps .row").filter({ hasText: "Greyhawk region" });
  await expect(row).toBeVisible();
  await expect(row.getByRole("link", { name: "Edit" })).toBeVisible();
  await expect(row).toContainText("Copied from the setting");
  await expect(page.getByRole("button", { name: "Import a world map" })).toBeVisible();
  await heading.evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e/screenshots/campaign-world-maps-1280x800.png" });
});

// The portraits plan's checks (Task 10): the campaign page's portrait style redraws its sample and the party's sheets in
// ink and wash, and the party sidebar on the play screen too; Connections saves a (fake) Replicate token, says "Set",
// lists Replicate among the painters at once, never shows the token, and removes it. Replicate is never called: the
// token is never tested and nothing is painted. The style goes back to illustrated at the end, for the specs after this.
const TOKEN = "tok-SECRET-XYZZY";
// The paper of portraitgen's ink-and-wash style (web/vendor/portraitgen/src/styles/inkwash.js).
const INK_PAPER = "#efe5cf";

test("the portrait style redraws the portraits, and Connections keeps the token to itself", async ({ page, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  await page.goto(`/campaigns/${campaign.id}?tab=party`);
  const sheets = page.locator(".sheets");
  const sample = page.locator(".campaign-portraits").getByRole("img", { name: "A sample portrait" });
  const style = page.getByLabel("Portrait style");
  await expect(style).toHaveValue("illustrated");
  await expect(sample.locator("svg")).toBeVisible();
  expect(await sample.innerHTML()).not.toContain(INK_PAPER);
  const garrek = sheets.getByRole("img", { name: /^Garrek/ }).first();
  await expect(garrek.locator("svg")).toBeVisible();
  expect(await garrek.innerHTML()).not.toContain(INK_PAPER);

  // Ink and wash: saved at once, and the sample and the sheets redraw.
  const saved = page.waitForResponse((r) => r.url().endsWith("/play/options") && r.request().method() === "PUT");
  await style.selectOption("inkwash");
  expect((await saved).ok()).toBe(true);
  await expect.poll(() => sample.innerHTML()).toContain(INK_PAPER);
  await expect.poll(() => garrek.innerHTML()).toContain(INK_PAPER);
  await page.getByRole("heading", { name: "Portraits" }).evaluate((el) => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e/screenshots/portrait-style-1280x800.png" });
  const state = await (await request.get(`/api/campaigns/${campaign.id}/play/state`)).json();
  expect(state.portrait_style).toBe("inkwash");

  // The play screen's party is in it too, after a reload.
  await page.goto(`/play/${campaign.id}`);
  const party = page.getByRole("region", { name: "Party" });
  await expect.poll(() => party.getByRole("img", { name: "Garrek" }).innerHTML()).toContain(INK_PAPER);

  // Connections, the owner's section of Preferences: a token saved is "Set", Replicate is a painter at once, the field is
  // empty.
  await page.goto("/preferences");
  await expect(page.getByRole("heading", { level: 2, name: "Connections" })).toBeVisible();
  const replicate = page.getByRole("group", { name: "Replicate" });
  await expect(replicate).toContainText("Token: Not set");
  await expect(page.locator("option", { hasText: "Replicate" })).toHaveCount(0);
  const field = replicate.getByLabel("Token");
  await expect(field).toHaveAttribute("type", "password");
  await field.fill(TOKEN);
  await replicate.getByRole("button", { name: "Save" }).click();
  await expect(replicate).toContainText("Token: Set");
  await expect(field).toHaveValue("");
  await expect(page.locator("option", { hasText: "Replicate" }).first()).toBeAttached();
  expect(await page.content()).not.toContain(TOKEN);
  const connections = await request.get("/api/connections");
  expect(await connections.text()).not.toContain(TOKEN);
  expect((await connections.json()).replicate).toEqual({ state: "set" });
  await page.screenshot({ path: "e2e/screenshots/connections-1280x800.png" });

  // Remove asks first, then the token and Replicate are gone.
  await replicate.getByRole("button", { name: "Remove" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Remove the Replicate token?");
  await dialog.getByRole("button", { name: "Remove" }).click();
  await expect(replicate).toContainText("Token: Not set");
  await expect(page.locator("option", { hasText: "Replicate" })).toHaveCount(0);
  expect(await page.content()).not.toContain(TOKEN);

  // Back to illustrated, as the campaign started.
  const json = { headers: { "Content-Type": "application/json" } };
  const back = await request.put(`/api/campaigns/${campaign.id}/play/options`, { ...json, data: { portrait_style: "illustrated" } });
  expect(back.ok()).toBe(true);
});
