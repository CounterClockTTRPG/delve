// A novel in a real browser (novelization plan Task 8), against `delve serve` with a fake `claude`: the owner
// novelizes the crypt's campaign as a short story on its page and watches the chapters being written, reads it with
// its table of contents, on a desktop and a phone, and opens its print view. An organiser account seated at the same
// table sees no Novels: not on the campaign page, not in the reader, not through the API. Screenshots in
// e2e/screenshots/.
//
// It runs after the world maps' spec (by file order), so the campaign has been played and its page keeps its earlier
// screenshots without a novel; the faithful book's spec, last, makes a campaign of its own. The fake writer's answers
// are tests/e2e/test_a_novel.py's (`novel_answer`): an outline of three chapters, then each chapter in a few seconds.
import { expect, test } from "@playwright/test";

const TITLE = "The Saint's Silver";
const CHAPTERS = ["The Stair Down", "What Pippa Kept", "The Sealed Door"];
const FIRST_LINE = "The stair was older than the chapel above it";
const INSTRUCTIONS = "Tell it from Pippa's side, and keep the Prior a mystery.";

test("novelize a campaign, read it, print it; an organiser account sees no Novels", async ({ page, browser, request }) => {
  const campaigns: { id: string; name: string }[] = await (await request.get("/api/campaigns")).json();
  const campaign = campaigns.find((c) => c.name === "The Crypt of Saint Vellis")!;

  // Novelize on the campaign page: a short story, with instructions.
  await page.goto(`/campaigns/${campaign.id}?tab=novels`);
  const novels = page.locator("section.novels");
  await expect(novels.getByRole("heading", { name: "Novels" })).toBeVisible();
  await expect(novels).toContainText("No novels yet.");
  await novels.getByLabel("Short story").check();
  await novels.getByLabel("Instructions").fill(INSTRUCTIONS);
  await expect(novels.getByLabel("All sessions")).toBeChecked();
  await novels.getByRole("button", { name: "Novelize" }).click();

  // The progress: the novel is being written, chapter by chapter, and Novelize waits.
  const row = novels.locator(".novel-row");
  await expect(row).toHaveAttribute("data-status", "writing");
  await expect(row.locator(".tag")).toHaveText("Being written");
  await expect(row).toContainText(`Short story · Classic · ${INSTRUCTIONS.slice(0, 60).trimEnd()}`);
  await expect(row.locator(".novel-progress")).toContainText(/[12] of 3 chapters/, { timeout: 30_000 });
  await expect(novels.getByRole("button", { name: "Novelize" })).toBeDisabled();
  await expect(novels.getByRole("note")).toContainText("Novel: The Crypt of Saint Vellis");
  await novels.getByRole("heading", { name: "Novels" }).evaluate((h) => h.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: "e2e/screenshots/novelize-1280x800.png" });
  await expect(row).toHaveAttribute("data-status", "done", { timeout: 60_000 });
  await expect(row.locator(".tag")).toHaveText("Done");
  await expect(row.getByRole("link", { name: TITLE })).toBeVisible();
  await expect(novels.getByRole("button", { name: "Novelize" })).toBeEnabled();

  // The job's end notification links to the reader; it is closed, so it hides nothing of the page.
  const notice = page.getByRole("link", { name: "Read the novel" });
  await expect(notice).toHaveAttribute("href", await row.getByRole("link", { name: TITLE }).getAttribute("href") ?? "");
  await page.getByRole("button", { name: "Close the notification" }).click();
  await expect(notice).toBeHidden();

  // The reader: the title, the table of contents linking to each chapter, and the chapters' text.
  await row.getByRole("link", { name: TITLE }).click();
  await expect(page).toHaveURL(/\/novels\/[^/]+$/);
  const novelPath = new URL(page.url()).pathname;
  await expect(page.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
  const contents = page.getByRole("navigation", { name: "Contents" });
  await expect(contents.getByRole("link")).toHaveText(CHAPTERS);
  for (const name of CHAPTERS) await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
  await expect(page.locator("article")).toContainText(FIRST_LINE);
  await page.screenshot({ path: "e2e/screenshots/novel-reader-1280x800.png" });
  await contents.getByRole("link", { name: CHAPTERS[1] }).click();
  await expect(page).toHaveURL(/#chapter-2$/);

  // The reader on a phone.
  const phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const phone = await phoneContext.newPage();
  await phone.goto(novelPath);
  await expect(phone.getByRole("heading", { level: 1, name: TITLE })).toBeVisible();
  await expect(phone.getByRole("navigation", { name: "Contents" }).getByRole("link")).toHaveText(CHAPTERS);
  const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await phone.screenshot({ path: "e2e/screenshots/novel-reader-390x844.png" });
  await phoneContext.close();

  // The print view: a title page, then each chapter on a page of its own.
  await page.getByRole("link", { name: "Print the novel" }).click();
  await expect(page).toHaveURL(new RegExp(`${novelPath}/print$`));
  await expect(page.locator("[data-part=title]")).toContainText(TITLE);
  await expect(page.locator("[data-part=chapter]")).toHaveCount(3);
  await expect(page.locator("[data-part=chapter]").first()).toContainText(FIRST_LINE);
  await page.screenshot({ path: "e2e/screenshots/novel-print-1280x800.png" });
  await page.emulateMedia({ media: "print" });
  const breaks = await page
    .locator("[data-part=chapter]")
    .evaluateAll((sections) => sections.map((s) => getComputedStyle(s).breakBefore));
  expect(breaks).toEqual(["page", "page", "page"]);
  await page.emulateMedia({ media: "screen" });

  // An organiser account seated at the same table: it sees no Novels anywhere (they are the owner's alone).
  const novelId = novelPath.split("/").pop()!;
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign.id}/invite`)).json();
  const seatContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const joined = await seatContext.request.post(`/api/join/${token}/account`, {
    data: { username: "ori.novels", password: "correct horse battery", display_name: "Ori", language: "en", role: "player" },
  });
  expect(joined.status()).toBe(201);
  const accountId = (await joined.json()).account.id as string;
  const made = await request.put(`/api/accounts/${accountId}`, { data: { organiser: true } });
  expect(made.ok(), await made.text()).toBe(true);
  expect((await seatContext.request.get("/api/preferences")).status()).toBe(200);
  for (const path of [`/api/novels?campaign_id=${campaign.id}`, `/api/novels/${novelId}`]) {
    const refused = await seatContext.request.get(path);
    expect(refused.status()).toBe(403);
    expect(await refused.text()).not.toContain(TITLE);
  }
  const seat = await seatContext.newPage();
  // The campaign page, an organiser's, has no Novels tab.
  await seat.goto(`/campaigns/${campaign.id}`);
  await expect(seat.getByRole("heading", { level: 1, name: campaign.name })).toBeVisible();
  await expect(seat.getByRole("tab", { name: "Novels" })).toHaveCount(0);
  await expect(seat.locator("body")).not.toContainText(TITLE);
  // The reader and the print view are refused.
  for (const path of [novelPath, `${novelPath}/print`]) {
    await seat.goto(path);
    await expect(seat.getByRole("alert")).toBeVisible();
    await expect(seat.locator("body")).not.toContainText(TITLE);
    await expect(seat.locator("body")).not.toContainText(FIRST_LINE);
  }
  await seat.close();
  // The seat leaves the table, so no later spec waits for it.
  expect((await seatContext.request.post(`/api/campaigns/${campaign.id}/leave`, { data: {} })).status()).toBe(204);
  await seatContext.close();
});
