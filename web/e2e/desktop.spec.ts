// The desktop's extras in a real browser, against the same fake server as the other specs, at 1280×800: the play
// screen's split dragged and remembered across a reload, the command palette (Ctrl K) going to a campaign, the
// shortcuts' help, and a campaign row's menu. It changes nothing on the server, and each test's browser context is
// fresh, so the later specs see Delve as it was. Screenshots in e2e/screenshots/.
import { expect, test } from "@playwright/test";

test("the play screen's split is dragged, and its widths survive a reload", async ({ page, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  await page.goto(`/play/${campaign.id}`);
  const divider = page.getByRole("separator", { name: "Resize the panes" });
  await expect(divider).toBeVisible();
  const aside = page.getByTestId("play-aside");
  const before = (await aside.boundingBox())!.width;

  const handle = (await divider.boundingBox())!;
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x - 200, handle.y + handle.height / 2, { steps: 8 });
  await page.mouse.up();
  const after = (await aside.boundingBox())!.width;
  expect(after).toBeGreaterThan(before + 150);
  // The input box still fits the window.
  const composer = (await page.getByTestId("composer").boundingBox())!;
  expect(composer.y + composer.height).toBeLessThanOrEqual(800);
  await page.screenshot({ path: "e2e/screenshots/desktop-split-1280x800.png" });

  await page.reload();
  await expect(divider).toBeVisible();
  expect(Math.abs((await aside.boundingBox())!.width - after)).toBeLessThan(4);

  // The arrow keys move the divider too.
  await divider.focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(async () => (await aside.boundingBox())!.width).toBeLessThan(after - 2);
});

test("Ctrl K goes anywhere, and ? lists the shortcuts", async ({ page, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  await page.goto("/modules");
  await expect(page.getByRole("heading", { name: "Modules" })).toBeVisible();
  await page.keyboard.press("Control+k");
  const input = page.getByPlaceholder("Type a campaign, a module, a setting or an action…");
  await expect(input).toBeFocused();
  await input.fill(`play ${campaign.name}`);
  await expect(page.getByRole("option", { name: `Play ${campaign.name}` })).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/desktop-palette-1280x800.png" });
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/play/${campaign.id}$`));

  // g then c: the campaigns.
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("g");
  await page.keyboard.press("c");
  await expect(page).toHaveURL(/\/campaigns$/);

  await page.keyboard.press("Shift+Slash");
  const help = page.getByRole("dialog", { name: "Keyboard shortcuts" });
  await expect(help).toBeVisible();
  await expect(help).toContainText("Go anywhere: campaigns, modules, settings, actions");
  await page.screenshot({ path: "e2e/screenshots/desktop-shortcuts-1280x800.png" });
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
});

test("a campaign row's actions are in its menu", async ({ page, request }) => {
  const [campaign] = await (await request.get("/api/campaigns")).json();
  await page.goto("/campaigns");
  await page.getByRole("button", { name: `Actions for ${campaign.name}` }).click();
  const menu = page.getByRole("menu");
  await expect(menu.getByRole("menuitem")).toHaveText(["Play", "Campaign page", "Carry the party on", "Delete"]);
  await page.screenshot({ path: "e2e/screenshots/desktop-row-menu-1280x800.png" });
  await menu.getByRole("menuitem", { name: "Campaign page" }).click();
  await expect(page).toHaveURL(new RegExp(`/campaigns/${campaign.id}$`));
});
