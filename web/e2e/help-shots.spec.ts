// The help's pictures (DEL-212), `make help-shots`: Chromium against `delve serve` with a fake `claude`, as the other
// browser checks, on the crypt's campaign after one beat. Each picture is a part of a screen, cropped, sometimes with
// one thing ringed, as a PNG in e2e/screenshots/help/; scripts/help_images.py makes them the WebP pictures the help
// topics show (web/public/help/). Skipped unless DELVE_HELP_SHOTS is set, so `make e2e-browser` doesn't redraw them.
import { expect, test, type Locator, type Page } from "@playwright/test";

test.skip(!process.env.DELVE_HELP_SHOTS, "only for make help-shots");

const OUT = "e2e/screenshots/help";

/**
 * `target` cropped with `pad` pixels around it (within the window, and above `above`), as `name`. `ring` is drawn
 * round with the accent colour first, and taken off after.
 */
async function shot(
  page: Page,
  name: string,
  target: Locator,
  { pad = 12, ring, above }: { pad?: number; ring?: Locator; above?: Locator } = {},
) {
  await target.scrollIntoViewIfNeeded();
  if (ring) await ring.evaluate((el) => el.setAttribute("data-help-ring", ""));
  await page.waitForTimeout(250);
  const box = await target.boundingBox();
  expect(box, name).not.toBeNull();
  const view = page.viewportSize()!;
  const x = Math.max(0, box!.x - pad);
  const y = Math.max(0, box!.y - pad);
  const clip = {
    x,
    y,
    width: Math.min(view.width, box!.x + box!.width + pad) - x,
    height: Math.min(view.height, box!.y + box!.height + pad) - y,
  };
  // Stop short of `above`, a part laid over the foot of the target (the table talk over the side column).
  const over = above ? await above.boundingBox() : null;
  if (over && over.y > clip.y) clip.height = Math.min(clip.height, over.y - 4 - clip.y);
  await page.screenshot({ path: `${OUT}/${name}.png`, clip });
  if (ring) await ring.evaluate((el) => el.removeAttribute("data-help-ring"));
}

const RING = `[data-help-ring] { outline: 3px solid #c2410c !important; outline-offset: 3px; border-radius: 4px; }`;

test("the help's pictures", async ({ page, browser, request }) => {
  test.setTimeout(300_000);
  // Every tour seen, so no offer stands in front of a picture; the tour's own picture starts it from Help.
  await page.addInitScript(() => {
    for (const id of ["play", "new-campaign", "campaign", "preferences"]) localStorage.setItem(`delve.tour.${id}`, "1");
  });
  const campaigns = await (await request.get("/api/campaigns")).json();
  const campaign = campaigns[0].id as string;

  // The owner's first account, before there is one: the login page offers it.
  await page.goto("/login");
  await page.addStyleTag({ content: RING });
  const firstOwner = page.locator(".first-owner");
  if (await firstOwner.count()) await shot(page, "first-owner", firstOwner.locator("xpath=.."), { pad: 0, ring: firstOwner });

  // The play screen after one beat: the party made, the story told.
  await page.goto(`/play/${campaign}`);
  await page.addStyleTag({ content: RING });
  const story = page.getByTestId("story");
  const composer = page.getByTestId("composer");
  const tavern = page.getByTestId("tavern");
  if (await tavern.isVisible().catch(() => false)) await tavern.getByTestId("tavern-back").click();
  await composer.locator("textarea").fill("Make us a fighter and a thief, then we go down into the crypt.");
  await composer.locator("textarea").press("Enter");
  await expect(story).toContainText("go down the worn stairs", { timeout: 60_000 });
  await expect(page.getByTestId("thinking")).toBeHidden({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Garrek", exact: true })).toBeVisible();
  // The prior's line, said in full and at rest.
  await expect(story.locator(".said[data-live='false']").last()).toBeVisible({ timeout: 30_000 });
  await expect(story).toContainText("Dust and old incense");

  await composer.locator("textarea").fill("We light a torch and look around the chapel.");
  await shot(page, "play-composer", composer, { pad: 16 });

  // Ask the DM: the answer, for this seat alone.
  await page.getByTestId("mode-ask").click();
  await composer.locator("textarea").fill("What does surprise do?");
  await page.getByTestId("ask").click();
  const asked = story.getByTestId("asked").last();
  await expect(asked).toContainText("A surprised character can't act", { timeout: 30_000 });
  await shot(page, "ask-the-dm-answer", asked, { pad: 16 });
  await page.getByTestId("mode-own").click();

  // Table talk, at the foot of the side column, with Raise hand ringed.
  const aside = page.getByTestId("play-aside");
  await aside.getByRole("tab", { name: /^Table/ }).click();
  const talk = page.getByTestId("talk-panel");
  await talk.getByTestId("talk-box").locator("textarea, input").first().fill("Back in five, refilling the tea.");
  const raise = page.getByRole("button", { name: "Raise hand" });
  await shot(page, "table-talk", talk, { pad: 8, ring: (await raise.count()) ? raise.first() : undefined });
  await aside.getByRole("tab", { name: /^Party/ }).click();

  // The host's invite, on the Table tab.
  await aside.getByRole("tab", { name: /^Table/ }).click();
  const invite = page.getByTestId("invite-panel");
  if (await invite.isVisible().catch(() => false)) {
    // Not this machine's own address: an example one, in a public page.
    await page.getByTestId("invite-url").evaluate((el) => ((el as HTMLInputElement).value = "https://delve.example/join/6Jq2hX…"));
    await page.getByTestId("invite-loopback").evaluate((el) => el.remove()).catch(() => undefined);
    // Above the QR code, which still holds this machine's link.
    await shot(page, "invite-panel", page.getByTestId("invite-panel"), { pad: 12, above: page.getByTestId("invite-qr") });
  }
  await aside.getByRole("tab", { name: /^Party/ }).click();

  // A character's sheet.
  await page.getByRole("button", { name: "Garrek", exact: true }).click();
  const drawer = page.locator(".sheet-drawer");
  await expect(drawer).toBeVisible();
  await shot(page, "character-sheet", drawer, { pad: 0 });
  await page.keyboard.press("Escape");

  // The tour of the play screen, from Help, at its story step.
  await page.getByTestId("nav-help").click();
  await page.getByRole("button", { name: "Take the tour: The play screen" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/tour-play.png` });
  await page.keyboard.press("Escape");

  // An organiser's screens: a new campaign, its schedule, New module and the map editor.
  await page.goto("/campaigns");
  await page.addStyleTag({ content: RING });
  await shot(page, "new-campaign-form", page.locator("#new-campaign"), { pad: 12 });
  await page.goto(`/campaigns/${campaign}`);
  await page.addStyleTag({ content: RING });
  const schedule = page.getByTestId("table-schedule");
  await schedule.scrollIntoViewIfNeeded();
  await shot(page, "schedule-form", schedule, { pad: 12 });
  await page.goto("/modules/new");
  await page.addStyleTag({ content: RING });
  await page.waitForTimeout(500);
  await shot(page, "new-module-ways", page.locator("section.page").first(), { pad: 0 });
  await page.goto(`/maps/${encodeURIComponent(campaigns[0].module_id)}/crypt`);
  await expect(page.locator(".monaco-editor .view-lines")).toContainText("Crypt of Saint Vellis", { timeout: 30_000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${OUT}/map-editor.png` });

  // Owner's Preferences: Backends (the jobs, the image style), Connections, Storage's backup.
  await page.goto("/preferences?tab=backends");
  await page.addStyleTag({ content: RING });
  const backends = page.getByRole("tabpanel");
  await expect(backends).toBeVisible();
  await shot(page, "backends-jobs", backends.locator("table, .backends, form").first(), { pad: 12 });
  const style = page.getByText("Image style", { exact: true }).first();
  await shot(page, "image-style", style.locator("xpath=ancestor::*[self::section or self::fieldset or self::div][1]"), { pad: 16 });
  await page.goto("/preferences?tab=connections");
  await page.addStyleTag({ content: RING });
  const connections = page.getByRole("tabpanel");
  await expect(connections).toBeVisible();
  await page.waitForTimeout(500);
  // Replicate and assetgen, above Google login (whose redirect URIs name this machine).
  await shot(page, "connections-tab", connections, { pad: 8, above: page.getByText("Google login", { exact: true }).first() });
  await page.goto("/preferences?tab=storage");
  await page.addStyleTag({ content: RING });
  await expect(page.getByRole("tabpanel")).toBeVisible();
  const backup = page.getByText("Back up daily at").first();
  if (await backup.count()) await shot(page, "backup-store", backup.locator("xpath=ancestor::section[1]"), { pad: 12 });
  else await page.screenshot({ path: `${OUT}/backup-store.png` });

  // A sign-up waiting on the Players page.
  await request.put("/api/sign-up", { data: { open: true } });
  await request.post("/api/sign-up", {
    data: { username: "tamsin.reed", password: "a long enough password", display_name: "Tamsin", note: "Ana's friend, Saturday table" },
  });
  await page.goto("/preferences/players");
  await page.addStyleTag({ content: RING });
  const waiting = page.locator(".players-waiting");
  await expect(waiting).toContainText("tamsin.reed");
  await shot(page, "players-waiting", waiting, { pad: 12, ring: waiting.getByRole("button", { name: "Let in" }).first() });
  await request.put("/api/sign-up", { data: { open: false } });

  // A phone: the play screen and its tabs.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await phone.addInitScript(() => localStorage.setItem("delve.tour.play", "1"));
  const small = await phone.newPage();
  await small.goto(`/play/${campaign}`);
  await expect(small.getByTestId("phone-tabs")).toBeVisible();
  await small.waitForTimeout(500);
  await small.screenshot({ path: `${OUT}/phone-tabs.png` });
  await phone.close();
});
