// Faithful modules in a real browser (faithful modules Task 29), against `delve serve` with a fake `claude`
// (tests/e2e/fake_play_server.py), which answers the faithful book's calls by their prompt with the answers of
// tests/e2e/test_a_faithful_book.py: a house and a ship, each keyed from 1, a map plate for each, a roster and a page
// of handouts.
// - the book converts through the API, and one draft follows per map page; the ship's is kept;
// - the house's draft over its book page (Review), on a laptop and on a phone;
// - the map editor on the ship's drafted map;
// - the pregens in the module editor, and in party creation, where the host asks the DM to make them;
// - a story of 120 entries (the fake's beats after the party's narrate a line each), which a seat that joins late
//   scrolls back to its start.
// Screenshots at 1280x800 and 390x844 in e2e/screenshots/.
//
// It runs last (file order), and makes its module, campaign and story itself at its start, so no earlier spec sees
// them. The fake's fourth beat is its party's (the third is the tavern's).
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const python = process.env.DELVE_E2E_PYTHON ?? "uv run python";
const DESKTOP = { width: 1280, height: 800 };
const PHONE = { width: 390, height: 844 };
// The fixture's map pages (tests/e2e/test_a_faithful_book.py's MAP_PAGES): one draft each.
const MAP_PAGES = 2;
const STORY = 120;
const SHIP_MAP = "the-ghost-ship";
const ACTS = ["We listen at the door.", "Caine checks the floor for traps.", "We go on, slowly.", "Aldon lifts the lantern."];

type Draft = { id: string; name: string; page: string | null; maps: { name: string }[] };
type Conversion = { status: string; error: string | null; module_id: string | null };

async function until<T>(probe: () => Promise<T | undefined | false>, what: string, timeout = 120_000): Promise<T> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const found = await probe();
    if (found) return found;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`no ${what} in ${timeout / 1000} s`);
}

async function shoot(page: Page, name: string) {
  const { width, height } = page.viewportSize()!;
  const size = width === PHONE.width ? `phone-${width}x${height}` : `${width}x${height}`;
  await page.screenshot({ path: `e2e/screenshots/${name}-${size}.png` });
}

async function storyLength(request: APIRequestContext, campaign: string): Promise<number> {
  const story = await (await request.get(`/api/campaigns/${campaign}/story?limit=200`)).json();
  return story.entries.length;
}

// Scroll the story back to its start: the story itself on a laptop, the page on a phone; each earlier page loads as
// the top comes into sight, and keeps the entry being read in place, so it takes a scroll per page.
async function scrollBack(page: Page) {
  const start = page.getByText("The start of the story");
  for (let n = 0; n < 20; n++) {
    await page.getByTestId("story").evaluate((story) => {
      story.scrollTop = 0;
      document.scrollingElement!.scrollTop = 0;
    });
    await page.waitForTimeout(400);
    if ((await start.count()) && (await page.getByRole("button", { name: "Load earlier" }).count()) === 0) break;
  }
  await page.getByTestId("story").evaluate((story) => {
    story.scrollTop = 0;
    document.scrollingElement!.scrollTop = 0;
  });
  await expect(start).toBeInViewport();
}

test("a faithful book: a draft over its page, the drafted map, the pregens, and a story scrolled back", async ({
  page,
  browser,
  request,
}, testInfo) => {
  test.setTimeout(300_000);

  // The book, converted through the API: its two map plates are drafted after it, one job after the other.
  const book = testInfo.outputPath("the-sinister-house.pdf");
  execSync(`${python} -m tests.e2e.fake_play_server --faithful-book "${book}"`, { cwd: ".." });
  const started = await request.post("/api/conversions/pdf?title=The%20Sinister%20House&mode=draft&thorough=false", {
    headers: { "Content-Type": "application/pdf" },
    data: readFileSync(book),
  });
  expect(started.status(), await started.text()).toBe(202);
  const { id } = await started.json();
  const done = await until(async () => {
    const now: Conversion = await (await request.get(`/api/conversions/${id}`)).json();
    return now.status !== "running" && now;
  }, "end of the conversion");
  expect(done.status, done.error ?? "").toBe("done");
  const moduleId = done.module_id!;
  const drafts = await until(async () => {
    const open: Draft[] = await (await request.get(`/api/modules/${moduleId}/map-drafts`)).json();
    return open.length === MAP_PAGES && open;
  }, "drafts of the map pages");
  const house = drafts.find((d) => d.page === "map-page-3")!;
  const ship = drafts.find((d) => d.page === "map-page-4")!;
  expect(house.maps.map((m) => m.name)).toEqual(["haunted-house-ground-floor", "haunted-house-cellar"]);
  const kept = await request.post(`/api/modules/${moduleId}/map-drafts/${ship.id}/keep`, { data: {} });
  expect(kept.status(), await kept.text()).toBe(201);

  // The house's draft over its book page: the page beside the draft, level by level.
  await page.setViewportSize(DESKTOP);
  await page.goto(`/modules/${moduleId}`);
  await page.getByRole("tab", { name: "Maps" }).click();
  const listed = page.getByRole("region", { name: "Drafts" });
  await expect(listed.getByTestId("map-draft")).toHaveCount(1);
  await listed.getByRole("button", { name: "Review" }).click();
  const review = page.getByRole("dialog", { name: `Review the draft ${house.name}` });
  const bookPage = review.getByRole("img", { name: "The book's page map-page-3" });
  await expect(bookPage).toBeVisible();
  await expect.poll(() => bookPage.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(review.getByRole("tablist", { name: "Levels" }).getByRole("tab")).toHaveCount(2);
  await expect(review.locator("svg").first()).toBeVisible();
  await shoot(page, "draft-review");
  await page.setViewportSize(PHONE);
  await expect(bookPage).toBeVisible();
  await shoot(page, "draft-review");
  await page.keyboard.press("Escape");

  // The map editor on the ship's drafted map: its code and its drawing.
  await page.setViewportSize(DESKTOP);
  await page.goto(`/maps/${moduleId}/${SHIP_MAP}`);
  await expect(page.locator(".monaco-editor").first()).toBeVisible();
  await expect(page.locator(".monaco-editor").first()).toContainText("Captain");
  // The drawing, once the source has settled: the book's rooms with their labels.
  const drawn = page.locator("svg text", { hasText: "Galley" });
  await expect(drawn.first()).toBeVisible();
  await expect(page.getByText("No preview.", { exact: false })).toHaveCount(0);
  await shoot(page, "map-editor-drafted");
  await page.setViewportSize(PHONE);
  await page.getByRole("tab", { name: "Drawing" }).click();
  await expect(page.getByLabel("Zoom in")).toBeVisible();
  await expect(drawn.first()).toBeVisible();
  await shoot(page, "map-editor-drafted");

  // The pregens in the module editor: the roster's two, Caine's form open.
  await page.setViewportSize(DESKTOP);
  await page.goto(`/modules/${moduleId}`);
  await page.getByRole("tab", { name: "Pregens", exact: true }).click();
  await expect(page.getByRole("button", { name: /Aldon/ })).toBeVisible();
  await page.getByRole("button", { name: /Caine/ }).click();
  await expect(page.locator("#entity-pregens-name")).toHaveValue("Caine");
  await shoot(page, "module-pregens");
  await page.setViewportSize(PHONE);
  await expect(page.locator("#entity-pregens-name")).toHaveValue("Caine");
  await page.locator("#entity-pregens-name").evaluate((field) => field.scrollIntoView({ block: "start" }));
  await shoot(page, "module-pregens");

  // A campaign on the module, with no party yet: the host is offered the pregens.
  const ready = await request.patch(`/api/modules/${moduleId}`, { data: { draft: false } });
  expect(ready.ok(), await ready.text()).toBe(true);
  const made = await request.post("/api/campaigns", { data: { name: "The Sinister House", module_id: moduleId } });
  expect(made.status(), await made.text()).toBe(201);
  const campaign: string = (await made.json()).id;
  await page.setViewportSize(DESKTOP);
  await page.goto(`/play/${campaign}`);
  const picker = page.getByRole("group", { name: "The module's pregenerated characters" });
  await expect(picker.getByRole("checkbox", { name: /Aldon/ })).toBeChecked();
  await expect(picker.getByRole("checkbox", { name: /Caine/ })).toBeChecked();
  await shoot(page, "party-pregens");
  await page.setViewportSize(PHONE);
  await page.getByTestId("tab-party").click();
  const party = page.getByTestId("phone-screen");
  await expect(party.getByRole("checkbox", { name: /Caine/ })).toBeVisible();
  await shoot(page, "party-pregens");

  // The host asks the DM to make them: the fake's beat makes the party from module_pregens.
  await party.getByRole("button", { name: "Ask the DM to make them" }).click();
  await until(async () => {
    const state = await (await request.get(`/api/campaigns/${campaign}/play/state`)).json();
    const names = state.party.map((pc: { name: string }) => pc.name).join(", ");
    return state.beat === null && names === "Aldon, Caine" && state;
  }, "the party");

  // A story of 120 entries: the party's beat, then short beats, each an act and the DM's line.
  for (let n = 0; (await storyLength(request, campaign)) < STORY; n++) {
    const acted = await request.post(`/api/campaigns/${campaign}/act`, { data: { text: ACTS[n % ACTS.length] } });
    expect(acted.status(), await acted.text()).toBe(202);
    await until(async () => (await (await request.get(`/api/campaigns/${campaign}/play/state`)).json()).beat === null, "the beat's end");
  }

  // Dee joins late, in a browser of her own, and scrolls the story back to its start.
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign}/invite`)).json();
  const dee = await browser.newContext({ viewport: DESKTOP });
  const joined = await dee.request.post(`/api/join/${token}/account`, {
    data: { username: "dee", password: "correct horse battery", display_name: "Dee", language: "en", role: "player" },
  });
  expect(joined.status()).toBe(201);
  const seat = await dee.newPage();
  await seat.goto(`/play/${campaign}`);
  await expect(seat.getByRole("button", { name: "Load earlier" })).toBeVisible();
  await expect(seat.getByText("The start of the story")).toHaveCount(0);
  await scrollBack(seat);
  await expect(seat.getByTestId("story")).toContainText("Aldon and Caine stand at the gate of the old house.");
  await shoot(seat, "story-history");
  await seat.setViewportSize(PHONE);
  await seat.reload();
  await expect(seat.getByRole("button", { name: "Load earlier" })).toBeVisible();
  await scrollBack(seat);
  await shoot(seat, "story-history");
  expect(await seat.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(PHONE.width);
  await dee.close();
});
