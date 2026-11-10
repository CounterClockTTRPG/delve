// The play screen in a real browser, against `delve serve` with a fake `claude` (plan 2b Task 10): Act, the story and
// the thinking indicator, a reload in the middle of the beat, Ask the DM, a character sheet, the party and the map
// above the fold at 1280x800, and screenshots on a laptop (1280x800), a tablet (820x1180) and a phone (390x844) in
// e2e/screenshots/. Prior Anselm's line (portraits plan Task 10) comes in live: its words grow while his portrait
// talks, then it is whole, and a reload shows it whole and at rest, never played again. The fresh campaign opens while the
// first page is blank, shot as gathering-1280x800.png, until the first act starts the session (DEL-199).
import { expect, test } from "@playwright/test";

// The fake DM's `say` in the first beat (tests/e2e/fake_play_server.py ANSELM_SAYS).
const ANSELM_SAYS = "Thank the saint you have come. Something stirs below the chapel, and the brothers will not go down.";

type SaidState = { live: boolean; text: string };
type SaidWindow = { saidStates: SaidState[] };

/**
 * In the page, from its first script on: every state the newest said line goes through (`data-live` and its words),
 * each change once, in `window.saidStates`.
 */
function recordSaidLine() {
  const states: SaidState[] = [];
  (window as unknown as SaidWindow).saidStates = states;
  new MutationObserver(() => {
    const lines = document.querySelectorAll(".said");
    const line = lines[lines.length - 1];
    if (!line) return;
    const state = {
      live: line.getAttribute("data-live") === "true",
      text: line.querySelector("[data-testid='said-text']")?.textContent ?? "",
    };
    const last = states[states.length - 1];
    if (!last || last.live !== state.live || last.text !== state.text) states.push(state);
  }).observe(document, { subtree: true, childList: true, characterData: true, attributes: true });
}

test("play a beat, reload in the middle of it, ask the DM, open a sheet", async ({ page, request }) => {
  const campaigns = await (await request.get("/api/campaigns")).json();
  expect(campaigns).toHaveLength(1);
  // The play screen's tour seen, so its offer stands in front of nothing.
  await page.addInitScript(() => localStorage.setItem("delve.tour.play", "1"));
  await page.goto(`/play/${campaigns[0].id}`);

  const story = page.getByTestId("story");
  const composer = page.getByTestId("composer").locator("textarea");
  await expect(page.getByRole("heading", { name: "The Crypt of Saint Vellis" })).toBeVisible();

  // Before the first act the story's first page is blank; alone at the table, the first act starts the session
  // (DEL-199).
  await expect(story).toContainText("The first page is blank");
  await expect(page.getByText("The session starts with your first act.")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/gathering-1280x800.png" });

  // Act: the beat runs, the DM's pacing line streams in, and the thinking indicator shows.
  await composer.fill("Make us a fighter and a thief, then we go down into the crypt.");
  await composer.press("Enter");
  await expect(story).toContainText("Make us a fighter and a thief");
  await expect(page.getByTestId("thinking")).toBeVisible();
  await expect(story).toContainText("Let me roll up your party.");
  await expect(page.getByTestId("act")).toBeDisabled();

  // Reload in the middle of the beat: the story rebuilds and the beat is still running. The reloaded page writes down
  // every state the prior's line goes through from the moment it loads, so the check below reads what the line did,
  // however late it looks: the talk window is short, and the waits for the beat's end can outlast it.
  await page.addInitScript(recordSaidLine);
  await page.reload();
  await expect(story).toContainText("Make us a fighter and a thief");
  await expect(story).toContainText("Let me roll up your party.");
  await expect(page.getByTestId("thinking")).toBeVisible();
  // The line comes after the reload, so it comes in live, not from history.
  await expect(story.locator(".said")).toHaveCount(0);

  // The beat ends: the narration, the party in the sidebar, and Act again.
  await expect(story).toContainText("go down the worn stairs", { timeout: 30_000 });
  await expect(page.getByTestId("thinking")).toBeHidden();
  await expect(page.getByRole("button", { name: "Garrek", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Pippa", exact: true })).toBeVisible();

  // The prior's line, its own entry beside his portrait: the words grow while he talks, then the line is whole.
  const said = story.locator(".said").last();
  const saidText = said.getByTestId("said-text");
  await expect(said.getByRole("img", { name: "Prior Anselm, afraid" })).toBeVisible();
  await expect(said.locator("svg")).toBeVisible();
  await expect(saidText).toHaveText(ANSELM_SAYS, { timeout: 30_000 });
  await expect(said).toHaveAttribute("data-live", "false", { timeout: 15_000 });
  // What the line did: live from its first state, its words a growing prefix with at least one part of the line shown,
  // then whole, and only then at rest.
  const states = await page.evaluate(() => (window as unknown as SaidWindow).saidStates);
  expect(states[0]?.live, JSON.stringify(states)).toBe(true);
  const resting = states.findIndex((s) => !s.live);
  expect(resting, JSON.stringify(states)).toBeGreaterThan(0);
  const talking = states.slice(0, resting);
  talking.forEach((s, i) => {
    expect(ANSELM_SAYS.startsWith(s.text), JSON.stringify(states)).toBe(true);
    expect(s.text.length).toBeGreaterThanOrEqual(talking[i - 1]?.text.length ?? 0);
  });
  expect(
    talking.some((s) => s.text.length > 0 && s.text.length < ANSELM_SAYS.length),
    JSON.stringify(states),
  ).toBe(true);
  expect(states.slice(resting).every((s) => !s.live && s.text === ANSELM_SAYS), JSON.stringify(states)).toBe(true);
  await expect(story).toContainText("Dust and old incense");
  await said.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/said-line-1280x800.png" });
  // A reload shows it whole and at rest: a line already shown never plays again.
  await page.reload();
  await expect(story.locator(".said").last().getByTestId("said-text")).toHaveText(ANSELM_SAYS);
  await expect(story.locator(".said[data-live='true']")).toHaveCount(0);

  // Ask the DM: the answer is in the story, folded, for this seat alone (plan 7 Task 18).
  await page.getByTestId("mode-ask").click();
  await composer.fill("What does surprise do?");
  await page.getByTestId("ask").click();
  const asked = story.getByTestId("asked").last();
  await expect(asked).toContainText("A surprised character can't act for one round");
  await expect(asked).toContainText("Only you");
  await page.getByTestId("mode-own").click();

  // Beside the story, the Party, Maps and Table tabs: the party's first card above the fold, and the map one click
  // away, its top above the fold too (walkthrough P1).
  await page.evaluate(() => window.scrollTo(0, 0));
  const aside = page.getByTestId("play-aside");
  const firstCard = await page.locator(".party-member").first().boundingBox();
  expect(firstCard).not.toBeNull();
  expect(firstCard!.y + firstCard!.height).toBeLessThanOrEqual(800);
  await page.screenshot({ path: "e2e/screenshots/play-1280x800.png" });
  await aside.getByRole("tab", { name: "Maps" }).click();
  const map = await page.getByRole("region", { name: "Map" }).boundingBox();
  expect(map).not.toBeNull();
  expect(map!.y).toBeLessThan(800);
  await page.screenshot({ path: "e2e/screenshots/play-maps-1280x800.png" });
  // The host's controls, on the Table tab, are folded.
  await aside.getByRole("tab", { name: /^Table/ }).click();
  await expect(page.getByTestId("host-table")).toBeVisible();
  await expect(page.getByTestId("host-table")).not.toHaveAttribute("open", "");
  await aside.getByRole("tab", { name: /^Party/ }).click();

  // The input box is at the bottom of the window, with the story filling the height above it.
  const box = await page.getByTestId("composer").boundingBox();
  expect(box!.y + box!.height).toBeGreaterThan(800 - 64);
  expect(box!.y + box!.height).toBeLessThanOrEqual(800);

  // Who acts: one click picks a character, the button says who, and Whole party goes back.
  const actFor = page.getByTestId("act-for");
  await expect(actFor).toContainText("Acting for: whole party");
  await actFor.click();
  await expect(page.getByRole("menu")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/play-acting-for-1280x800.png" });
  await page.getByRole("menuitemradio", { name: "Pippa" }).click();
  await expect(actFor).toContainText("Acting for: Pippa");
  await actFor.click();
  await page.getByRole("menuitemradio", { name: "Whole party" }).click();
  await expect(actFor).toContainText("Acting for: whole party");

  // A character sheet opens from anywhere on a party card, and Escape closes it.
  await page.locator(".party-member").first().locator(".hp-bar").click();
  const sheet = page.getByTestId("sheet-drawer");
  await expect(sheet).toBeVisible();
  await expect(sheet).toContainText("Garrek");
  await page.screenshot({ path: "e2e/screenshots/play-sheet-1280x800.png" });
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();

  // A tablet: the panels stack, the story first.
  await page.setViewportSize({ width: 820, height: 1180 });
  await expect(story).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/play-820x1180.png" });

  // A phone: the map opens on the whole known map, not zoomed into one room (walkthrough P7).
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByTestId("tab-map").click();
  await expect(page.getByRole("button", { name: "Focus on the party" })).toHaveAttribute("aria-pressed", "false");
  // The map takes the screen's height, not a fixed box with room to spare under it (DEL-323).
  const mapHeight = await page.evaluate(() => document.querySelector(".phone-screen .play-map")!.getBoundingClientRect().height);
  expect(mapHeight).toBeGreaterThan(844 * 0.6);
  await page.screenshot({ path: "e2e/screenshots/play-map-390x844.png" });
  await page.getByRole("button", { name: "Back to the story" }).click();
  await expect(story).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/play-390x844.png" });
  // The play screen fits the phone's window: the page doesn't scroll, the story scrolls in its box, and the head and
  // the input box stay in view above the play tabs (DEL-311).
  const fit = await page.evaluate(() => {
    const box = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
    return {
      page: document.documentElement.scrollHeight,
      window: window.innerHeight,
      head: box(".play-head").top,
      composer: box(".composer").bottom,
      tabs: box(".play-tabs").top,
      story: getComputedStyle(document.querySelector(".story")!).overflowY,
      storyHeight: box(".story").height,
    };
  });
  expect(fit.page).toBeLessThanOrEqual(fit.window);
  expect(fit.head).toBeGreaterThanOrEqual(0);
  expect(fit.composer).toBeLessThanOrEqual(fit.tabs);
  expect(fit.story).toBe("auto");
  // More of the story than the head and the input box (DEL-323): it had 285 px of the 844, now well over half.
  expect(fit.storyHeight).toBeGreaterThan(fit.window * 0.55);
  await story.locator(".said").last().scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/said-line-390x844.png" });

  // One bar at the foot (DEL-188): the play tabs; the app's areas, Help, the language and Log out are under Menu.
  const areas = page.getByRole("navigation", { name: "Areas" });
  await expect(areas).toBeHidden();
  expect(fit.tabs + 48).toBeGreaterThanOrEqual(fit.window - 1);
  await page.getByTestId("tab-menu").click();
  await expect(areas).toBeVisible();
  await expect(areas.getByRole("link", { name: "Campaigns", exact: true })).toBeVisible();
  await expect(areas.getByRole("combobox", { name: "Language" })).toBeVisible(); // DEL-292
  await page.screenshot({ path: "e2e/screenshots/play-menu-390x844.png" });
  await page.keyboard.press("Escape");
  await expect(areas).toBeHidden();

  // The host's Claude usage in the head, in reach on a phone (DEL-283).
  await page.route("**/play/usage", (route) =>
    route.fulfill({
      json: {
        usage: {
          at: new Date().toISOString(),
          status: "allowed",
          windows: [
            { name: "five_hour", utilization: 0.42, resets_at: new Date(Date.now() + 3 * 3600_000).toISOString() },
            { name: "seven_day", utilization: 0.81, resets_at: new Date(Date.now() + 4 * 86400_000).toISOString() },
          ],
        },
      },
    }),
  );
  await page.reload();
  const usage = page.getByTestId("account-usage");
  await expect(usage).toContainText("42%");
  const meter = (await usage.boundingBox())!;
  expect(meter.y).toBeGreaterThanOrEqual(0);
  expect(meter.x + meter.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "e2e/screenshots/play-usage-390x844.png" });

  // The campaign's log (DEL-324), from the campaign's menu on Campaigns: the story from the start, its pages by session.
  await expect(page.getByTestId("campaign-log-link")).toHaveCount(0);
  await page.goto("/campaigns");
  await page.getByRole("button", { name: /^Actions for / }).first().click();
  await page.getByRole("menuitem", { name: "Campaign log" }).click();
  await expect(page).toHaveURL(/\/campaigns\/[^/]+\/log$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("Make us a fighter and a thief, then we go down into the crypt.")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/campaign-log-390x844.png" });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({ path: "e2e/screenshots/campaign-log-1280x800.png" });
  // The whole log as a Markdown file (DEL-346).
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByTestId("log-markdown").click()]);
  expect(download.suggestedFilename()).toMatch(/-log\.md$/);
  const saved = await download.path();
  const { readFileSync } = await import("node:fs");
  const text = readFileSync(saved!, "utf-8");
  expect(text).toContain("Make us a fighter and a thief, then we go down into the crypt.");
  expect(text.startsWith("# ")).toBe(true);
});
