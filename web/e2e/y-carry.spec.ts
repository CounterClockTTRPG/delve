// Carry the party on in a real browser (carry-the-party-on plan Task 7), against `delve serve` with a fake `claude`:
// the owner carries the crypt's party into the module New module made, watches the history being written, reads both
// versions, edits them, and is asked before Write again would replace the edit. A player seat at the new table reads
// the table's version under the play screen's History tab, without the DM's Loose ends. On a desktop and a phone.
// Screenshots in e2e/screenshots/.
//
// It runs after the novel's spec (by file order), whose job has ended, so the history's job isn't refused; it sets the
// crypt's campaign to complete, which no later spec plays (the faithful book's makes a campaign of its own). The fake
// writer's answers are tests/e2e/fake_play_server.py's (`history_answer`), a few seconds each.
import { expect, test, type Page } from "@playwright/test";

const CRYPT = "The Crypt of Saint Vellis";
const NAME = "Beyond the Crypt";
const PHONE = { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true };
const PUBLIC_LINE = "Prior Anselm";
const DM_ONLY = "Loose ends";
const EDIT = "The Prior promised them a bed at the chapel whenever they pass.";

async function noOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("carry the party on, read and edit its history; a player reads the table's", async ({ page, browser, request }) => {
  const campaigns: { id: string; name: string; module_id: string }[] = await (await request.get("/api/campaigns")).json();
  const crypt = campaigns.find((c) => c.name === CRYPT)!;
  const modules: { id: string; title: string; draft: boolean }[] = await (await request.get("/api/modules")).json();
  const onward = modules.find((m) => !m.draft && m.id !== crypt.module_id)!;
  expect(onward).toBeTruthy();
  // No job runs (the novel's has ended), or the history would wait for Write again.
  await expect
    .poll(async () => ((await (await request.get("/api/conversions")).json()) as { status: string }[]).some((c) => c.status === "running"))
    .toBe(false);

  // The form on a phone first, while the crypt's campaign is still in progress: opened from `?carry`.
  const phoneContext = await browser.newContext(PHONE);
  const phone = await phoneContext.newPage();
  await phone.goto(`/campaigns/${crypt.id}?carry`);
  const phoneForm = phone.getByRole("region", { name: "Carry the party on" });
  await expect(phoneForm.getByRole("checkbox", { name: "Garrek" })).toBeChecked();
  // Scrolled to its fields, so its buttons clear the tab bar.
  await phoneForm.getByRole("group", { name: "Who goes" }).evaluate((group) => group.scrollIntoView({ block: "center" }));
  await expect(phoneForm.getByRole("button", { name: "Carry the party on" })).toBeInViewport();
  await noOverflow(phone);
  await phone.screenshot({ path: "e2e/screenshots/carry-form-390x844.png" });

  // The form on the desktop, from the campaign page's button: the living PCs ticked, the old campaign's world.
  await page.goto(`/campaigns/${crypt.id}`);
  await page.getByRole("button", { name: "Carry the party on" }).click();
  const form = page.getByRole("region", { name: "Carry the party on" });
  await expect(form.getByRole("checkbox", { name: "Garrek" })).toBeChecked();
  await expect(form.getByRole("checkbox", { name: "Pippa" })).toBeChecked();
  await expect(form.getByRole("checkbox", { name: /Prior Anselm/ })).toHaveCount(0);
  await expect(form.getByLabel("New campaign's name")).toHaveValue(CRYPT);
  await expect(form.getByLabel("Setting")).toHaveValue("greyhawk");
  await expect(form.getByLabel("Module").locator("option")).not.toHaveCount(0);
  await form.getByLabel("Module").selectOption(onward.id);
  await form.getByLabel("New campaign's name").fill(NAME);
  await form.getByRole("heading", { name: "Carry the party on" }).evaluate((h) => h.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e/screenshots/carry-form-1280x800.png" });
  await form.getByRole("button", { name: "Carry the party on" }).click();

  // The new campaign's page: carried on from the crypt, its history being written, then both versions.
  await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
  await expect(page).not.toHaveURL(new RegExp(`/campaigns/${crypt.id}$`));
  const newId = new URL(page.url()).pathname.split("/").pop()!;
  const section = page.getByTestId("history-section");
  await expect(section.getByRole("link", { name: CRYPT })).toHaveAttribute("href", `/campaigns/${crypt.id}`);
  const history = section.locator(".history");
  await expect(history).toHaveAttribute("data-status", "writing");
  await expect(section.getByRole("progressbar")).toBeVisible();
  await expect(history).toHaveAttribute("data-status", "done", { timeout: 60_000 });
  await expect(section.getByRole("tab", { name: "The DM's" })).toHaveAttribute("aria-selected", "true");
  await expect(section.locator(".history-text")).toContainText(DM_ONLY);
  await expect(section.locator(".history-text")).toContainText(PUBLIC_LINE);

  // The job's end notification links to the History; it is closed, so it hides nothing of the page.
  const notice = page.getByRole("link", { name: "Read the history" });
  await expect(notice).toHaveAttribute("href", `/campaigns/${newId}#history`);
  await page.getByRole("button", { name: "Close the notification" }).click();
  await expect(notice).toBeHidden();
  await section.getByRole("heading", { name: "History" }).evaluate((h) => h.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e/screenshots/history-host-1280x800.png" });
  await section.getByRole("tab", { name: "The table's" }).click();
  await expect(section.locator(".history-text")).toContainText(PUBLIC_LINE);
  await expect(section.locator(".history-text")).not.toContainText(DM_ONLY);

  // Edit both texts: the history is marked edited. Write again then asks first; Cancel keeps the edit.
  await section.getByRole("button", { name: "Edit" }).click();
  const tableText = section.getByLabel("The table's history");
  await tableText.fill(`${await tableText.inputValue()}\n\n${EDIT}`);
  await section.getByRole("button", { name: "Save" }).click();
  await expect(section.locator(".tag", { hasText: "Edited" })).toBeVisible();
  await section.getByRole("tab", { name: "The table's" }).click();
  await expect(section.locator(".history-text")).toContainText(EDIT);
  await section.getByRole("button", { name: "Write again" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("Your edit of the history will be replaced.");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(section.locator(".history-text")).toContainText(EDIT);

  // The crypt's page: complete, and carried on to the new campaign.
  await page.goto(`/campaigns/${crypt.id}`);
  await expect(page.getByLabel("Status")).toHaveValue("complete");
  await expect(page.getByTestId("history-section").getByRole("link", { name: NAME })).toHaveAttribute("href", `/campaigns/${newId}`);

  // The host's History on a phone.
  await phone.goto(`/campaigns/${newId}#history`);
  const phoneSection = phone.getByTestId("history-section");
  await expect(phoneSection.locator(".history")).toHaveAttribute("data-status", "done");
  await phoneSection.getByRole("heading", { name: "History" }).evaluate((h) => h.scrollIntoView({ block: "start" }));
  await noOverflow(phone);
  await phone.screenshot({ path: "e2e/screenshots/history-host-390x844.png" });
  await phoneContext.close();

  // A player seat at the new table: the History tab, the table's text with the host's edit, and no Loose ends.
  const { join_token: token } = await (await request.get(`/api/campaigns/${newId}/invite`)).json();
  const seatContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const joined = await seatContext.request.post(`/api/join/${token}/account`, {
    data: { username: "ori.carry", password: "correct horse battery", display_name: "Ori", language: "en", role: "player" },
  });
  expect(joined.status()).toBe(201);
  const told = await seatContext.request.get(`/api/campaigns/${newId}/history`);
  expect(Object.keys(await told.json()).sort()).toEqual(["status", "table_md"]);
  const seat = await seatContext.newPage();
  await seat.goto(`/play/${newId}`);
  await seat.getByTestId("play-aside").getByRole("tab", { name: "Maps" }).click();
  await seat.getByRole("tab", { name: "History" }).click();
  const panel = seat.getByTestId("history-panel");
  await expect(panel).toContainText(EDIT);
  await expect(panel).toContainText(PUBLIC_LINE);
  await expect(seat.locator("body")).not.toContainText(DM_ONLY);
  await seat.screenshot({ path: "e2e/screenshots/history-tab-1280x800.png" });

  // The same seat on a phone: History is a screen of the bottom bar.
  const seatPhoneContext = await browser.newContext({ ...PHONE, storageState: await seatContext.storageState() });
  const seatPhone = await seatPhoneContext.newPage();
  await seatPhone.goto(`/play/${newId}`);
  await expect(seatPhone.getByTestId("tab-history")).toBeInViewport({ ratio: 1 });
  await seatPhone.getByTestId("tab-history").click();
  const phonePanel = seatPhone.getByTestId("phone-screen").getByTestId("history-panel");
  await expect(phonePanel).toContainText(PUBLIC_LINE);
  await expect(seatPhone.locator("body")).not.toContainText(DM_ONLY);
  await noOverflow(seatPhone);
  await seatPhone.screenshot({ path: "e2e/screenshots/history-tab-390x844.png" });
  await seatPhoneContext.close();

  // The seat leaves the table, so no later spec waits for it.
  expect((await seatContext.request.post(`/api/campaigns/${newId}/leave`, { data: {} })).status()).toBe(204);
  await seatContext.close();
});
