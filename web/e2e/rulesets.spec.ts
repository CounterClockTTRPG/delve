// The Rulesets area in a real browser (rulesets plan Task 7), against `delve serve` with a fake `claude` and OSRIC,
// installed as a pack (DEL-307): the owner reaches it from the nav and sees Monsters. A player seat on a phone opens
// the play header's Rulesets link in a new tab, finds *Web* through School = evocation (OSRIC's), opens its page, and
// finds no Monsters card and a "not found" at the monsters' address. Screenshots in e2e/screenshots/.
//
// It runs after the play screen's spec, on its campaign, and before the settings' and the table's (by file order); its
// seat plays no character and leaves the table at the end, so the later specs find only their own.
import { expect, test } from "@playwright/test";

test("Rulesets: the owner's Monsters; a player's tab finds Web by its school, and meets no monster", async ({ page, browser, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign.id}/invite`)).json();

  // The owner: Rulesets in the nav, the ruleset's sections, Monsters among them.
  await page.goto("/");
  await page.getByRole("navigation").getByRole("link", { name: "Rulesets" }).click();
  await expect(page).toHaveURL(/\/rulesets$/);
  await page.getByRole("link", { name: "OSRIC 3.0" }).click();
  await expect(page).toHaveURL(/\/rulesets\/osric$/);
  await expect(page.getByRole("link", { name: /^Monsters/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /^Spells/ })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/rulesets-owner-1280x800.png" });

  // A player seat on a phone, playing no character. It joins by the API, one request, as the joins from one address
  // are limited to ten a minute and the later specs join through the page.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const joined = await phone.request.post(`/api/join/${token}/account`, {
    data: { username: "eli", password: "correct horse battery", display_name: "Eli", language: "en", role: "player" },
  });
  expect(joined.status()).toBe(201);
  const seat = await phone.newPage();
  await seat.goto(`/play/${campaign.id}`);
  await expect(seat.getByTestId("composer")).toBeVisible();

  // The play header's Rulesets link opens the campaign's ruleset in a new tab, naming the table (an account's area knows
  // its table by it); the table stays open in the first.
  const link = seat.locator("header.play-head").getByRole("link", { name: "Rulesets" });
  await expect(link).toHaveAttribute("href", `/rulesets/osric?campaign=${campaign.id}`);
  await expect(link).toHaveAttribute("target", "_blank");
  const [tab] = await Promise.all([phone.waitForEvent("page"), link.click()]);
  await expect(tab).toHaveURL(new RegExp(`/rulesets/osric\\?campaign=${campaign.id}$`));
  await expect(seat).toHaveURL(new RegExp(`/play/${campaign.id}$`));

  // No Monsters for a player, and no nav: the way back is to its table.
  await expect(tab.getByRole("link", { name: /^Spells/ })).toBeVisible();
  await expect(tab.getByRole("link", { name: /^Monsters/ })).toHaveCount(0);
  await expect(tab.getByRole("link", { name: "Back to the table" })).toHaveAttribute("href", `/play/${campaign.id}`);

  // Spells, School = evocation, then Web by its name.
  await tab.getByRole("link", { name: /^Spells/ }).click();
  await expect(tab.getByRole("heading", { name: "Spells", level: 1 })).toBeVisible();
  await tab.getByRole("combobox", { name: "School" }).selectOption("evocation");
  await expect(tab).toHaveURL(/school=evocation/);
  await tab.getByRole("searchbox", { name: "Filter by name" }).fill("Web");
  await expect(tab).toHaveURL(/q=Web/);
  await tab.getByRole("link", { name: "Web", exact: true }).click();

  // The spell's page: its fields and text, at 390 px with no sideways scroll.
  await expect(tab.getByRole("heading", { name: "Web", level: 1 })).toBeVisible();
  await expect(tab.getByText(/^evocation$/i)).toBeVisible();
  await expect(tab.getByText("Casting time", { exact: true })).toBeVisible();
  const [scrollWidth, clientWidth] = await tab.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
  await tab.screenshot({ path: "e2e/screenshots/rulesets-spell-390x844.png", fullPage: true });

  // The monsters' address, pasted: not found, naming nothing.
  await tab.goto("/rulesets/osric/monsters");
  await expect(tab.getByText("This page isn't in the ruleset.")).toBeVisible();
  await expect(tab.getByRole("heading", { name: "Monsters" })).toHaveCount(0);
  await tab.goto("/rulesets/osric/monsters/1");
  await expect(tab.getByText("This page isn't in the ruleset.")).toBeVisible();

  // Any other address sends the player's account to its tables.
  await tab.goto("/campaigns");
  await expect(tab).toHaveURL(/\/tables$/);
  await expect(tab.getByTestId(`my-table-${campaign.id}`)).toBeVisible();

  // The seat leaves the table, so the later specs find only their own.
  expect((await phone.request.post(`/api/campaigns/${campaign.id}/leave`, { headers: { "Content-Type": "application/json" }, data: {} })).ok()).toBe(true);
  await phone.close();
});
