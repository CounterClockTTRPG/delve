// The message board (DEL-297) in real browsers: the owner makes a zone ("The engine": everybody reads, accounts write,
// pictures on), Bo (a player account made by the crypt campaign's invite, as y-talk-pictures.spec.ts makes Mo) starts a
// topic with bold text and a picture, the owner quotes him and replies, Bo's board shows the zone with "1 new", a
// visitor with no login reads the topic and is asked to log in, and the owner's delete of Bo's post reads "Removed by a
// moderator". Screenshots of the topic on a laptop (1280x800) and a phone (390x844) in e2e/screenshots/. It plays no
// beat of the fake DM, makes no campaign, and deletes its zone at the end (Bo's seat at the crypt campaign stays).
import { expect, test } from "@playwright/test";

const PASSWORD = "correct horse battery";
const TITLE = "Could the DM roll morale in the open?";

test("a topic on the board: started, replied to, read by a visitor, moderated", async ({ page, request, playwright, browser, baseURL }) => {
  const campaigns: { id: string }[] = await (await request.get("/api/campaigns")).json();
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaigns[0].id}/invite`)).json();
  const joiner = await playwright.request.newContext({ baseURL });
  const joined = await joiner.post(`/api/join/${token}/account`, {
    data: { username: "bo-board", password: PASSWORD, display_name: "Bo", language: "en", role: "player" },
  });
  expect([201, 409]).toContain(joined.status());
  await joiner.dispose();

  const made = await request.post("/api/board/zones", { data: { name: "The engine", read: "everybody", write: "accounts", pictures: true } });
  expect(made.status(), await made.text()).toBe(201);
  const zone: string = (await made.json()).zone.id;
  const tourSeen = () => localStorage.setItem("delve.tour.play", "1");
  const bo = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  // Outside this machine (as through the owner's tunnel), so with no login the visitor is not the owner.
  const visitor = await browser.newContext({ viewport: { width: 1280, height: 800 }, extraHTTPHeaders: { "X-Forwarded-For": "203.0.113.25" } });
  try {
    await page.addInitScript(tourSeen);
    await bo.addInitScript(tourSeen);
    await visitor.addInitScript(tourSeen);

    // Bo logs in and starts the topic, bold text and a picture.
    const boPage = await bo.newPage();
    await boPage.goto("/login");
    await boPage.getByTestId("login-username").fill("bo-board");
    await boPage.getByTestId("login-password").fill(PASSWORD);
    await boPage.getByTestId("login-submit").click();
    await boPage.waitForURL(/\/home/);
    await boPage.goto(`/board/${zone}`);
    await boPage.getByRole("link", { name: "New topic" }).or(boPage.getByRole("button", { name: "New topic" })).first().click();
    await boPage.getByLabel("Title", { exact: true }).fill(TITLE);
    await boPage.getByLabel("Your post").fill("A **bold** question: do the monsters flee in plain sight?");
    await boPage.getByLabel("Add a picture").setInputFiles("e2e/avatar-300x200.png");
    await boPage.getByRole("button", { name: "Start the topic" }).click();
    await expect(boPage.getByRole("heading", { name: TITLE })).toBeVisible();
    await expect(boPage.getByTestId("board-post").locator("strong", { hasText: "bold" })).toBeVisible();
    await expect(boPage.getByTestId("board-post").locator("img").last()).toBeVisible();
    const topicUrl = boPage.url();
    // Bo leaves the topic for the board, so the owner's reply arrives while he is away (an open topic marks it read).
    await boPage.goto("/board");

    // The owner opens it, quotes Bo's post and replies.
    await page.goto(topicUrl);
    await expect(page.getByRole("heading", { name: TITLE })).toBeVisible();
    await page.getByRole("button", { name: "Quote" }).first().click();
    const box = page.getByLabel("Your reply");
    await expect(box).toHaveValue(/bold/);
    await box.press("Control+End");
    await box.pressSequentially("\n\nYes: it keeps the table honest.");
    await page.getByRole("button", { name: "Post", exact: true }).click();
    await expect(page.getByTestId("board-post")).toHaveCount(2);
    await expect(page.getByTestId("board-post").last()).toContainText("keeps the table honest");

    // Bo's board shows the zone with 1 new.
    await boPage.reload();
    const row = boPage.locator("li", { hasText: "The engine" });
    await expect(row.getByText("1 new")).toBeVisible();

    // A visitor, with no login, reads it and is asked to log in.
    const visitorPage = await visitor.newPage();
    await visitorPage.goto("/board");
    await visitorPage.getByRole("link", { name: "The engine" }).click();
    await visitorPage.getByRole("link", { name: TITLE }).click();
    await expect(visitorPage.getByRole("heading", { name: TITLE })).toBeVisible();
    await expect(visitorPage.getByRole("link", { name: "Log in to post" })).toBeVisible();

    // Screenshots: the topic on a laptop and on a phone, with no sideways scroll.
    await page.screenshot({ path: "e2e/screenshots/board-topic-1280x800.png" });
    await visitorPage.setViewportSize({ width: 390, height: 844 });
    await expect(visitorPage.getByRole("heading", { name: TITLE })).toBeVisible();
    expect(await visitorPage.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await visitorPage.screenshot({ path: "e2e/screenshots/board-topic-390x844.png" });

    // The owner deletes Bo's post; for Bo it reads "Removed by a moderator".
    await page.getByTestId("board-post").first().getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete" }).click();
    // The delete has landed before Bo loads the topic: the owner's own page shows the post removed.
    await expect(page.getByTestId("board-post").first()).toContainText("Removed by a moderator");
    await boPage.goto(topicUrl);
    await expect(boPage.getByText("Removed by a moderator")).toBeVisible();
  } finally {
    await bo.close();
    await visitor.close();
    await request.delete(`/api/board/zones/${zone}`);
  }
});
