// Pictures in table talk (DEL-294) in a real browser: the host allows them in the table options, picks a picture in
// the talk box, the line shows it and enlarges it on a click, and the host takes it down. It runs on play.spec.ts's
// campaign, and turns the option off again. A screenshot on a laptop (1280x800) in e2e/screenshots/.
import { expect, test } from "@playwright/test";

test("paste a picture into table talk, enlarge it, take it down", async ({ page, request, playwright, baseURL }) => {
  const campaigns: { id: string }[] = await (await request.get("/api/campaigns")).json();
  const campaign = campaigns[0].id;
  // Talk shows once someone else sits at the table: Mo joins by the invite, with an account of their own.
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign}/invite`)).json();
  const mo = await playwright.request.newContext({ baseURL });
  const joined = await mo.post(`/api/join/${token}/account`, {
    data: { username: "mo-pictures", password: "correct horse battery", display_name: "Mo", language: "en", role: "player" },
  });
  expect([201, 409]).toContain(joined.status());
  await mo.dispose();
  // The play screen's tour seen, so its offer stands in front of nothing.
  await page.addInitScript(() => localStorage.setItem("delve.tour.play", "1"));
  await page.goto(`/play/${campaign}`);
  const talk = page.getByTestId("talk-panel");
  await expect(talk.getByLabel("Add a picture")).toHaveCount(0);

  await page.getByRole("button", { name: "Table options" }).click();
  // Saved at once, the box shows what the server stored: a click, then the box ticked.
  const allowed = page.getByRole("checkbox", { name: "Pictures in table talk" });
  await allowed.click();
  await expect(allowed).toBeChecked();
  await expect.poll(async () => (await (await request.get(`/api/campaigns/${campaign}/play/options`)).json()).talk_pictures).toBe(true);
  await page.getByRole("button", { name: "Table options" }).click();
  await expect(page.getByRole("dialog", { name: "Table options" })).toBeHidden();

  try {
    await talk.getByLabel("Add a picture").setInputFiles("e2e/avatar-300x200.png");
    const open = talk.getByRole("button", { name: /^Enlarge: a picture from / }).last();
    await expect(open).toBeVisible();
    await expect(open.locator("img")).toHaveJSProperty("naturalWidth", 300);
    await page.screenshot({ path: "e2e/screenshots/talk-picture-1280x800.png" });
    await open.click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.getByRole("dialog").click();
    await expect(page.getByRole("dialog")).toBeHidden();

    await talk.getByRole("button", { name: /picture down$/ }).last().click();
    await expect(talk.getByText("Picture taken down").last()).toBeVisible();
    await expect(talk.getByRole("button", { name: /^Enlarge: a picture from / })).toHaveCount(0);
  } finally {
    await request.put(`/api/campaigns/${campaign}/play/options`, { data: { talk_pictures: false } });
  }
});
