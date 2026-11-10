// Edit portrait (DEL-238) in a real browser: portraitgen's own editor opens in a frame on the sheet's portrait, a
// reroll there changes it, and Save keeps what the editor shows as the PC's portrait. Shot as
// e2e/screenshots/portrait-editor-1280x800.png.
import { expect, test } from "@playwright/test";

test("edit a PC's portrait in portraitgen's editor and save it", async ({ page, request }) => {
  const campaigns = await (await request.get("/api/campaigns")).json();
  const cid = campaigns[0].id;
  // A PC of its own, made by the organiser, so this runs without a beat played first.
  const made = await request.post(`/api/campaigns/${cid}/characters`, { data: { name: "Tamsin" } });
  expect(made.ok()).toBe(true);
  const tamsin = (await made.json()).id;
  await page.goto(`/play/${cid}`);
  const tavern = page.getByTestId("tavern");
  const story = page.getByTestId("story");
  await expect(tavern.or(story)).toBeVisible();
  if (await tavern.isVisible()) await tavern.getByTestId("tavern-back").click();

  await page.locator(".party-member", { hasText: "Tamsin" }).locator(".hp-bar").click();
  const sheet = page.getByTestId("sheet-drawer");
  await expect(sheet).toContainText("Tamsin");
  await expect(sheet.getByRole("button", { name: "Repaint Tamsin's portrait" })).toHaveCount(0);
  await sheet.getByRole("button", { name: "Edit Tamsin's portrait" }).click();

  const frame = page.frameLocator("iframe.portrait-editor-frame");
  await expect(frame.getByRole("heading", { name: "Portrait Forge" })).toBeVisible();
  await expect(frame.locator("#preview svg")).toBeVisible();
  await frame.getByRole("button", { name: "Randomize" }).click();
  const seed = await frame.locator("#seed").inputValue();
  await page.screenshot({ path: "e2e/screenshots/portrait-editor-1280x800.png" });
  await page.getByRole("button", { name: "Save portrait" }).click();
  await expect(page.locator("iframe.portrait-editor-frame")).toHaveCount(0);

  const characters = await (await request.get(`/api/campaigns/${cid}/characters`)).json();
  const saved = characters.find((c: { id: string }) => c.id === tamsin);
  expect(saved.sheet.portrait.kind).toBe("traits");
  expect(saved.sheet.portrait.seed).toBe(seed);
  expect(saved.sheet.portrait.traits.seed).toBe(seed);
});
