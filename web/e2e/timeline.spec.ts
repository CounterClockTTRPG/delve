// The initiative timeline during a fight, against `delve serve` with a fake `claude` (table voice and fixes Task B2.4):
// the host acts in a campaign of its own, and the fake's fight beat (`FIGHT` in tests/e2e/fake_play_server.py) makes
// Mirela and Tansy, sets up a fight with two goblins with Mirela casting Sleep, thinks a while, rules Mirela hit, resolves
// the round and narrates it. Before the narration the strip shows the order and Mirela's span; after it, the spell
// interrupted. On desktop and on a phone (390x844), where it is one row that scrolls sideways and the page doesn't.
// Screenshots in e2e/screenshots/.
//
// It runs after thorough-conversion.spec.ts and before u-fixit.spec.ts (by file name), and plays the fake's fourth beat,
// after the tavern's: no spec between it and zz-faithful.spec.ts plays one. It deletes its campaign at the end.
import { expect, test, type Page } from "@playwright/test";

const json = { headers: { "Content-Type": "application/json" } };
const FIGHT_REPLY = "A sling stone cracks against Mirela's temple, and the words of her Sleep spell die on her lips.";

function mirelasSpan(page: Page) {
  return page.getByTestId("timeline").locator('[data-testid^="timeline-span-"]', { hasText: "Mirela" });
}

test("the timeline shows the fight's order and an ongoing spell, then the spell interrupted once it is told", async ({
  page,
  browser,
  request,
}) => {
  const [crypt] = await (await request.get("/api/campaigns")).json();
  const made = await request.post("/api/campaigns", { ...json, data: { name: "The Bramble Road", module_id: crypt.module_id } });
  expect(made.status(), await made.text()).toBe(201);
  const campaign: string = (await made.json()).id;
  try {
    // No fight yet: no strip. A new campaign is in its pregame, so the tavern opens (after the page's first read of the
    // table): wait for it and go back to the story, or the act below would be table talk.
    await page.goto(`/play/${campaign}`);
    await expect(page.getByTestId("tavern")).toBeVisible();
    await page.getByTestId("tavern-back").click();
    await expect(page.getByTestId("story")).toBeVisible();
    await expect(page.getByTestId("timeline")).toHaveCount(0);

    const composer = page.getByTestId("composer").locator("textarea");
    await composer.fill("We push on through the brambles.");
    await composer.press("Enter");

    // Initiative is rolled: the order and Mirela's span, while the DM still thinks and nothing is narrated.
    const strip = page.getByTestId("timeline");
    await expect(strip).toBeVisible({ timeout: 30_000 });
    await expect(strip).toHaveAttribute("data-layout", "axis");
    await expect(strip).toContainText("Round 1");
    // Each combatant stands on the axis, in view: none scrolled off the strip's end.
    for (const name of ["Mirela", "Tansy", "Goblin 1", "Goblin 2"])
      await expect(strip.locator('[data-testid^="timeline-slot-"]', { hasText: name })).toBeInViewport({ ratio: 1 });
    await expect(mirelasSpan(page)).toHaveAttribute("data-state", "ongoing");
    await expect(mirelasSpan(page)).toContainText("casting Sleep");
    await expect(page.getByTestId("story")).not.toContainText(FIGHT_REPLY);
    await strip.screenshot({ path: "e2e/screenshots/timeline-strip-ongoing.png" });

    // The round is told: the spell is marked interrupted, with why.
    await expect(page.getByTestId("story")).toContainText(FIGHT_REPLY, { timeout: 30_000 });
    await expect(mirelasSpan(page)).toHaveAttribute("data-state", "interrupted");
    await expect(mirelasSpan(page)).toContainText("interrupted: Mirela was hit");
    await page.screenshot({ path: "e2e/screenshots/timeline-desktop.png" });

    // A reload reads the same: the outcomes are stored as told.
    await page.reload();
    await expect(mirelasSpan(page)).toHaveAttribute("data-state", "interrupted");

    // Folded to its round, and open again (DEL-130).
    await page.getByRole("button", { name: "Fold the initiative" }).click();
    await expect(page.getByTestId("timeline")).toHaveAttribute("data-folded", "true");
    await expect(mirelasSpan(page)).toHaveCount(0);
    await page.getByTestId("timeline").screenshot({ path: "e2e/screenshots/timeline-folded.png" });
    await page.getByRole("button", { name: "Show the initiative" }).click();
    await expect(mirelasSpan(page)).toHaveAttribute("data-state", "interrupted");

    // On a phone: one thin row, scrolling sideways inside itself; the page doesn't.
    const phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
    const phone = await phoneContext.newPage();
    await phone.goto(`/play/${campaign}`);
    const row = phone.getByTestId("timeline");
    await expect(row).toBeVisible();
    await expect(row.locator('[data-layout="row"]')).toBeVisible();
    await expect(row).toContainText("Mirela");
    await expect(row).toContainText("interrupted: Mirela was hit");
    const overflow = await row.locator('[data-layout="row"]').evaluate((el) => getComputedStyle(el).overflowX);
    expect(overflow).toBe("auto");
    const width = await phone.evaluate(() => document.documentElement.scrollWidth);
    expect(width).toBeLessThanOrEqual(390);
    await phone.screenshot({ path: "e2e/screenshots/timeline-phone.png" });
    await phoneContext.close();
  } finally {
    // So the later specs see what they saw before.
    expect((await request.delete(`/api/campaigns/${campaign}`, json)).status()).toBe(204);
  }
});
