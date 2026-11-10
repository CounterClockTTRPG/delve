// Email (DEL-314) in real browsers, with no network: the owner turns the Email connection to Emailit (a fake key, the
// sender, this server's own address), and the fake server answers Emailit itself and shows what it was handed at
// GET /api/e2e/mail (tests/e2e/fake_play_server.py `fake_mail`; the app has no such route). Bo (a player account made by
// the crypt campaign's invite, as yz-board.spec.ts makes his) adds an address in Preferences and confirms it from the
// emailed link; asks for a new password by his username and opens the emailed link; the owner skips the table's next
// session with "Tell the players by email" and Bo hears; and Bo follows a topic and gets one mail for two replies.
// Screenshots of Preferences' Email section and Connections' Email row on a laptop (1280x800) and a phone (390x844),
// and on a phone of Next session with "Tell the players", the Write to the table dialog and the board's reply box with
// its follow box, in e2e/screenshots/. It plays no beat of the fake DM; it restores the connection and the schedule at its end.
import { expect, test, type Locator, type Page } from "@playwright/test";

const PASSWORD = "correct horse battery";
const NEW_PASSWORD = "a brand new horse staple";
const ADDRESS = "bo-mail@example.org";
const TOPIC = "Who carries the lantern?";

type Sent = { to: string; subject: string; text: string; headers: Record<string, string> };

const tourSeen = () => localStorage.setItem("delve.tour.play", "1");

/** The mail to `to` whose subject starts with `subject`, polled until it shows (the sender loop passes every 2 s). */
async function mailTo(page: Page, to: string, subject: RegExp): Promise<Sent[]> {
  let found: Sent[] = [];
  await expect
    .poll(async () => {
      const all: { messages: Sent[] } = await (await page.request.get("/api/e2e/mail")).json();
      found = all.messages.filter((m) => m.to === to && subject.test(m.subject));
      return found.length;
    }, { timeout: 30_000 })
    .toBeGreaterThan(0);
  return found;
}

function linkIn(mail: Sent, path: string): string {
  const match = mail.text.match(new RegExp(`https?://\\S+${path}\\S+`));
  expect(match, mail.text).not.toBeNull();
  return match![0];
}

/** A screenshot of the page, at the phone size it is set to, with `shown` in view and no sideways scroll. */
async function phoneShot(page: Page, shown: Locator, name: string): Promise<void> {
  await expect(shown).toBeVisible();
  await shown.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: `e2e/screenshots/${name}` });
}

function ymd(days: number): string {
  const d = new Date(Date.now() + days * 86_400_000);
  return d.toISOString().slice(0, 10);
}

test("email: an address confirmed, a password reset, a skipped session and a board reply", async ({ page, request, playwright, browser, baseURL }) => {
  test.setTimeout(120_000);
  const campaigns: { id: string }[] = await (await request.get("/api/campaigns")).json();
  const campaign = campaigns[0].id;
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign}/invite`)).json();
  const joiner = await playwright.request.newContext({ baseURL });
  const joined = await joiner.post(`/api/join/${token}/account`, {
    data: { username: "bo-mail", password: PASSWORD, display_name: "Bo", language: "en", role: "player" },
  });
  expect([201, 409]).toContain(joined.status());
  await joiner.dispose();

  // The owner turns Emailit on: a fake key, the sender and this server's own address for the links.
  const origin = baseURL!.replace(/\/$/, "");
  const put = await request.put("/api/connections/email", {
    data: { provider: "emailit", key: "em_e2e_fake_key_0123456789", sender: "Delve <noreply@example.org>", public_url: origin },
  });
  expect(put.status(), await put.text()).toBe(200);
  expect(await (await request.get("/api/mail/status")).json()).toEqual({ enabled: true });

  const bo = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const stranger = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  let zone: string | undefined;
  try {
    await page.addInitScript(tourSeen);
    await bo.addInitScript(tourSeen);
    await stranger.addInitScript(tourSeen);

    // Bo logs in and adds his address in Preferences: the link is on its way, and nothing else goes to it yet.
    const boPage = await bo.newPage();
    await boPage.goto("/login");
    await boPage.getByTestId("login-username").fill("bo-mail");
    await boPage.getByTestId("login-password").fill(PASSWORD);
    await boPage.getByTestId("login-submit").click();
    await boPage.waitForURL(/\/home/);
    await boPage.goto("/preferences");
    const section = boPage.getByRole("region", { name: "Email" });
    await expect(section).toBeVisible();
    await section.getByTestId("email-address").fill(ADDRESS);
    await section.getByTestId("email-send").click();
    await expect(section.getByTestId("email-pending")).toContainText(ADDRESS);
    const [confirm] = await mailTo(boPage, ADDRESS, /^Confirm your email address/);
    expect(confirm.headers["List-Unsubscribe"]).toBeUndefined(); // the always-go kinds have no off link

    // He opens the emailed link and presses the button; Preferences now shows the address as his.
    await boPage.goto(linkIn(confirm, "/account/email/"));
    await boPage.getByRole("button", { name: "Confirm the address" }).click();
    await expect(boPage.getByRole("status")).toContainText("Your address is confirmed.");
    await boPage.goto("/preferences");
    await expect(boPage.getByTestId("email-current")).toContainText(ADDRESS);
    await expect(section.getByRole("checkbox")).toHaveCount(2);
    await section.scrollIntoViewIfNeeded();
    await section.screenshot({ path: "e2e/screenshots/email-preferences-1280x800.png" });
    await boPage.setViewportSize({ width: 390, height: 844 });
    await expect(section).toBeVisible();
    expect(await boPage.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await section.scrollIntoViewIfNeeded();
    await section.getByRole("checkbox").last().scrollIntoViewIfNeeded();
    await boPage.mouse.wheel(0, 200); // the switches clear of the tab bar
    await boPage.screenshot({ path: "e2e/screenshots/email-preferences-390x844.png" });

    // A new password by username: the link comes to the confirmed address, and opening it sets the password.
    const lost = await stranger.newPage();
    await lost.goto("/login");
    await lost.getByTestId("forgot-open").click();
    await lost.getByTestId("forgot-username").fill("bo-mail");
    await lost.getByTestId("forgot-submit").click();
    await expect(lost.getByTestId("forgot-asked")).toBeVisible();
    const [reset] = await mailTo(lost, ADDRESS, /^Choose a new Delve password/);
    await lost.goto(linkIn(reset, "/account/link/"));
    await lost.getByTestId("link-password").fill(NEW_PASSWORD);
    await lost.getByTestId("link-password-again").fill(NEW_PASSWORD);
    await lost.getByTestId("link-submit").click();
    await lost.waitForURL(/\/home/);

    // A new password ends his other sessions, so the rest is done in the browser the reset logged in.
    // The owner skips the next session and tells the players by email: Bo's mail follows, with an off link.
    const set = await request.put(`/api/campaigns/${campaign}/schedule`, {
      data: { every_weeks: 1, first: ymd(7), start: "20:00", end: "22:00", time_zone: "Europe/Brussels" },
    });
    expect(set.status(), await set.text()).toBe(200);
    await page.goto(`/play/${campaign}`);
    await page.getByTestId("play-aside").getByRole("tab", { name: /^Table/ }).click();
    const controls = page.getByTestId("next-session-controls");
    await expect(controls).toBeVisible();
    await controls.getByTestId("next-tell").check();
    await controls.getByTestId("next-note").fill("Bring snacks next time.");
    await controls.getByTestId("next-skip").click();
    await expect(controls.getByTestId("next-told")).toContainText("1");
    const [skipped] = await mailTo(page, ADDRESS, /a session is skipped/);
    expect(skipped.text).toContain("Bring snacks next time.");
    expect(skipped.headers["List-Unsubscribe-Post"]).toBe("List-Unsubscribe=One-Click");

    // The board: Bo follows a topic and leaves; two replies make one email.
    const made = await request.post("/api/board/zones", { data: { name: "The lantern", read: "everybody", write: "accounts", pictures: false } });
    expect(made.status(), await made.text()).toBe(201);
    zone = (await made.json()).zone.id as string;
    const started = await request.post(`/api/board/zones/${zone}/topics`, { data: { title: TOPIC, text: "Somebody must hold it." } });
    expect(started.status(), await started.text()).toBe(201);
    const topic: string = (await started.json()).topic.id;
    await lost.goto(`/board/topics/${topic}`);
    const replyBox = lost.locator(".board-reply");
    await expect(replyBox.getByRole("checkbox", { name: "Email me about replies" })).toBeVisible();
    await lost.setViewportSize({ width: 390, height: 844 });
    await phoneShot(lost, replyBox, "email-board-reply-390x844.png");
    await lost.setViewportSize({ width: 1280, height: 800 });
    const follow = lost.getByRole("button", { name: "Follow", exact: true });
    await follow.click();
    await expect(lost.getByRole("button", { name: "Stop following" })).toHaveAttribute("aria-pressed", "true");
    await lost.goto("/board");
    for (const text of ["I will.", "No, I will."]) {
      const reply = await request.post(`/api/board/topics/${topic}/posts`, { data: { text } });
      expect(reply.status(), await reply.text()).toBe(201);
    }
    const [board] = await mailTo(lost, ADDRESS, /replied in/);
    expect(board.subject).toContain(TOPIC);
    expect(board.headers["List-Unsubscribe-Post"]).toBe("List-Unsubscribe=One-Click");
    // Mail goes oldest first: once a later message (the confirmation sent again) is out, a second board mail would be.
    const again = await lost.request.put("/api/account/email", { data: { address: ADDRESS } });
    expect(again.status(), await again.text()).toBe(202);
    await expect
      .poll(async () => {
        const all: { messages: Sent[] } = await (await lost.request.get("/api/e2e/mail")).json();
        return all.messages.filter((m) => m.to === ADDRESS && /^Confirm your email address/.test(m.subject)).length;
      }, { timeout: 30_000 })
      .toBe(2);
    const all: { messages: Sent[] } = await (await request.get("/api/e2e/mail")).json();
    expect(all.messages.filter((m) => m.to === ADDRESS && /replied in/.test(m.subject))).toHaveLength(1);

    // On a phone, the owner's Table panel: Next session with "Tell the players" ticked, then Write to the table to
    // some of it, the ticks and radios at their own size.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("navigation", { name: "Panels" }).getByRole("button", { name: "Table" }).click();
    const phoneControls = page.getByTestId("next-session-controls");
    await phoneControls.getByTestId("next-tell").check();
    await phoneControls.getByTestId("next-note").fill("Bring snacks next time.");
    await phoneShot(page, phoneControls, "email-next-session-390x844.png");
    await page.getByTestId("write-to-table").click();
    const dialog = page.getByRole("dialog", { name: "Write to the table" });
    await dialog.getByRole("radio").nth(1).check();
    await expect(dialog.getByRole("checkbox").first()).toBeVisible();
    await phoneShot(page, dialog, "email-write-390x844.png");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await page.setViewportSize({ width: 1280, height: 800 });

    // The owner's Connections row, on a laptop and on a phone.
    await page.goto("/preferences");
    await page.getByRole("tab", { name: "Connections" }).click();
    const row = page.getByRole("group", { name: "Email" });
    await row.scrollIntoViewIfNeeded();
    await expect(row).toBeVisible();
    await row.screenshot({ path: "e2e/screenshots/email-connection-1280x800.png" });
    await page.setViewportSize({ width: 390, height: 844 });
    await row.scrollIntoViewIfNeeded();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: "e2e/screenshots/email-connection-390x844.png" });
  } finally {
    await bo.close();
    await stranger.close();
    if (zone) await request.delete(`/api/board/zones/${zone}`);
    await request.put(`/api/campaigns/${campaign}/schedule`, { data: null });
    await request.delete("/api/connections/email");
  }
});
