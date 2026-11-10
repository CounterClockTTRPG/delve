// The Settings area and the play screen's Setting tab in a real browser (settings plan Task 15), against `delve serve`
// with a fake `claude`: Settings in the nav, Greyhawk's lore searched for Hardby, its page and a link followed (on a
// phone too), a fact added, and the DM's proposal (seeded by tests/e2e/fake_play_server.py) accepted on the Proposals
// tab. Then a player seat, joined by the link, reads Hardby and the accepted fact in its Setting tab, and never the
// install's DM-only fact, which holds the planted secret. Preferences open where the options were. Screenshots in
// e2e/screenshots/.
//
// It runs after the play screen's spec, on its campaign, and before the table's (by file order); its seat plays no
// character and leaves the table at the end, so the table's spec finds its own.
import { expect, test } from "@playwright/test";

const SECRET = "SECRET-XYZZY";
const PROPOSED = "The Free City's new harbour master is a half-orc.";
const ADDED = "The Green Dragon Inn serves a cider brewed in Hardby.";

test("Settings: search, a page, a link, a fact, a proposal accepted; the Setting tab; Preferences", async ({ page, browser, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign.id}/invite`)).json();

  // Settings in the nav, then Greyhawk, on its Lore tab.
  await page.goto("/");
  await page.getByRole("navigation").getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await page.getByRole("link", { name: "Greyhawk" }).click();
  await expect(page.getByRole("heading", { name: "Greyhawk", level: 1 })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Lore" })).toHaveAttribute("aria-selected", "true");

  // Search for Hardby, and open its page.
  await page.getByRole("searchbox", { name: "Search the lore" }).fill("Hardby");
  const hardby = page.getByRole("link", { name: "Hardby", exact: true });
  await expect(hardby).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/settings-lore-1280x800.png" });
  await hardby.click();
  await expect(page.getByRole("heading", { name: "Hardby", level: 1 })).toBeVisible();

  // A link in the page opens the page it names.
  const link = page.locator("a[data-page]").first();
  const target = (await link.getAttribute("data-page"))!;
  await link.click();
  await expect(page).toHaveURL(new RegExp(`/pages/${encodeURIComponent(target).replace(/[()'!*]/g, ".")}$`));
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveText("Hardby");

  // The page on a phone, the organiser's own browser.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const organiserPhone = await phone.newPage();
  await organiserPhone.goto("/settings/greyhawk/pages/Hardby");
  await expect(organiserPhone.getByRole("heading", { name: "Hardby", level: 1 })).toBeVisible();
  await organiserPhone.screenshot({ path: "e2e/screenshots/settings-page-phone-390x844.png" });
  await phone.close();

  // A fact added on the Facts tab.
  await page.goto("/settings/greyhawk?tab=facts");
  await page.getByLabel("Fact", { exact: true }).fill(ADDED);
  await page.getByRole("button", { name: "Add the fact" }).click();
  await expect(page.getByRole("tabpanel").locator("li", { hasText: ADDED })).toBeVisible();

  // The DM's proposal waits on the Proposals tab, from its campaign; accepted, it leaves the list.
  await page.getByRole("tab", { name: /Proposals/ }).click();
  const proposal = page.getByRole("tabpanel").locator("li", { hasText: PROPOSED });
  await expect(proposal).toBeVisible();
  await expect(proposal.getByRole("link", { name: campaign.name })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/settings-proposals-1280x800.png" });
  await proposal.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByText("No proposals wait for you.")).toBeVisible();

  // A player seat joins by the link, plays no character, and opens the Setting tab beside the map.
  const seatContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const seat = await seatContext.newPage();
  await seat.goto(`/join/${token}`);
  await seat.getByTestId("join-username").fill("dee.setting");
  await seat.getByTestId("join-password").fill("correct horse battery");
  await seat.getByTestId("join-name").fill("Dee");
  await seat.getByTestId("join-role-player").check();
  await seat.getByTestId("join-submit").click();
  await seat.getByTestId("join-play").click();
  await expect(seat).toHaveURL(new RegExp(`/play/${campaign.id}$`));
  await seat.getByTestId("play-aside").getByRole("tab", { name: "Maps" }).click();
  await seat.getByRole("tab", { name: "Setting" }).click();
  const panel = seat.getByTestId("setting-panel");
  await expect(panel.getByRole("heading", { name: "Greyhawk" })).toBeVisible();

  // Hardby, searched and read in the panel.
  await panel.getByRole("searchbox", { name: "Search the lore" }).fill("Hardby");
  await panel.getByRole("button", { name: "Hardby", exact: true }).click();
  await expect(panel.getByRole("heading", { name: "Hardby", exact: true })).toBeVisible();
  await seat.screenshot({ path: "e2e/screenshots/play-setting-1280x800.png" });

  // The facts: the accepted proposal and the added fact, the DM-only one nowhere.
  await panel.getByRole("tab", { name: "Facts" }).click();
  await expect(panel).toContainText(PROPOSED);
  await expect(panel).toContainText(ADDED);
  expect(await seat.content()).not.toContain(SECRET);

  // The same seat on a phone: the Setting screen from the bottom bar.
  const seatPhoneContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await seatPhoneContext.addCookies(await seatContext.cookies());
  const seatPhone = await seatPhoneContext.newPage();
  await seatPhone.goto(`/play/${campaign.id}`);
  await seatPhone.getByTestId("tab-setting").click();
  const screen = seatPhone.getByTestId("phone-screen");
  await screen.getByRole("tab", { name: "Facts" }).click();
  await expect(screen).toContainText(PROPOSED);
  expect(await seatPhone.content()).not.toContain(SECRET);
  await screen.getByText(PROPOSED).scrollIntoViewIfNeeded();
  await seatPhone.screenshot({ path: "e2e/screenshots/play-setting-phone-390x844.png" });
  await seatPhoneContext.close();

  // The seat leaves the table, so the table's spec finds only its own.
  expect((await seatContext.request.post(`/api/campaigns/${campaign.id}/leave`, { headers: { "Content-Type": "application/json" }, data: {} })).ok()).toBe(true);
  await seatContext.close();

  // Preferences, where the install's options were.
  await page.getByRole("navigation").getByRole("link", { name: "Preferences" }).click();
  await expect(page).toHaveURL(/\/preferences$/);
  await expect(page.getByRole("heading", { name: "Preferences", level: 1 })).toBeVisible();
});
