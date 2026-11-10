// Players and table talk in two real browsers, against `delve serve` with a fake `claude` (players and tavern Task H2,
// table talk as DEL-199 left it): the host on this machine, and Mira, who is outside (a visitor through a proxy on this
// machine, as through the owner's tunnel). Mira opens the invite, makes an account, sets a profile with an uploaded
// picture, sits at the table, talks with the host in the table talk panel and sees faces; the host starts the session,
// the fake DM opens the scene while the talk stays, and Mira may act; she logs out, and logs in on a fresh browser
// context to find her seat through My tables. Screenshots in e2e/screenshots/.
//
// It runs after table.spec.ts (by file name) and before thorough-conversion.spec.ts. It plays the fake's third beat
// (`TAVERN_REPLY`), the session's opening; timeline.spec.ts plays the fourth (the fight) and zz-faithful.spec.ts the
// fifth, and no other spec after it plays one (thorough-conversion, u-fixit, voice, world, worldmap, x-novels and
// y-carry play none; world.spec.ts only reads the world). It makes its own campaign and deletes it at the end, and
// makes no owner account, so this machine is still the owner for the later specs.
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const json = { headers: { "Content-Type": "application/json" } };
const PASSWORD = "correct horse battery";
const TAVERN_REPLY = "The innkeeper sets down two mugs, and the fire crackles in the hearth.";
const AVATAR = readFileSync(new URL("./avatar-300x200.png", import.meta.url));

function composer(page: Page) {
  return page.getByTestId("composer").locator("textarea");
}

/** The table talk panel's own box, beside the story's, which speaks only to the DM (DEL-199). */
function talkBox(page: Page) {
  return page.getByTestId("talk-box").locator("textarea");
}

/** The play screen's tour seen, so its offer stands in front of nothing. */
function tourSeen() {
  localStorage.setItem("delve.tour.play", "1");
}

test("an account joins by invite, sets a profile, talks at the table, plays, and finds its seat again", async ({ page, browser, request }) => {
  // The host's side: a campaign on the crypt, a PC, the invite.
  const [crypt] = await (await request.get("/api/campaigns")).json();
  const made = await request.post("/api/campaigns", { ...json, data: { name: "The Wayside Inn", module_id: crypt.module_id } });
  expect(made.status(), await made.text()).toBe(201);
  const campaign: string = (await made.json()).id;
  try {
    const wren = await request.post(`/api/campaigns/${campaign}/characters`, { ...json, data: { name: "Wren" } });
    expect(wren.status(), await wren.text()).toBeLessThan(300);
    const wrenId: string = (await wren.json()).id;
    const { join_token: token } = await (await request.get(`/api/campaigns/${campaign}/invite`)).json();

    // Mira, outside, opens the invite and makes an account.
    const miraContext = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      extraHTTPHeaders: { "X-Forwarded-For": "203.0.113.24" },
    });
    await miraContext.addInitScript(tourSeen);
    const mira = await miraContext.newPage();
    await mira.goto(`/join/${token}`);
    await mira.getByTestId("join-username").fill("wren.player");
    await mira.getByTestId("join-password").fill(PASSWORD);
    await mira.getByTestId("join-name").fill("Mira");
    await mira.getByTestId("join-language").selectOption("en");
    await mira.getByTestId("join-role-player").check();
    await mira.getByTestId("join-submit").click();
    await mira.getByTestId(`join-character-${wrenId}`).check();
    await mira.getByTestId("join-play").click();
    await expect(mira).toHaveURL(new RegExp(`/play/${campaign}$`));
    // The pregame: the table talk is there, and acting waits for the host to start the session.
    await expect(mira.getByTestId("talk-panel")).toBeVisible();
    await expect(mira.getByTestId("act")).toBeDisabled();

    // Her profile: an uploaded picture, then pronouns and the ember colour. The stored picture resets the form, so the
    // spec waits for the upload's answer before it fills it, and for the save's before it reads the profile.
    await mira.goto("/preferences");
    const uploaded = mira.waitForResponse((r) => r.url().endsWith("/api/account/avatar") && r.request().method() === "POST");
    await mira.getByTestId("profile-upload").setInputFiles({ name: "mira.png", mimeType: "image/png", buffer: AVATAR });
    expect((await uploaded).status()).toBe(200);
    await mira.getByTestId("profile-pronouns").fill("she/her");
    await mira.getByTestId("profile-colour-ember").check();
    const saved = mira.waitForResponse((r) => r.url().endsWith("/api/account/profile") && r.request().method() === "PUT");
    await mira.getByTestId("profile-save").click();
    expect((await saved).status()).toBe(200);
    const profile = await (await miraContext.request.get("/api/account/profile")).json();
    expect(profile.colour).toBe("ember");
    const avatar = await miraContext.request.get(`/api/profiles/${profile.id ?? profile.account_id}/avatar`);
    expect(avatar.status()).toBe(200);
    await mira.goto("/tables");
    await mira.getByTestId(`my-table-play-${campaign}`).click();
    await expect(mira).toHaveURL(new RegExp(`/play/${campaign}$`));
    const miraTalk = mira.getByTestId("talk-panel");
    await expect(miraTalk).toBeVisible();

    // The host's table talk is there too. They talk, and see each other's lines and Mira's face.
    await page.addInitScript(tourSeen);
    await page.goto(`/play/${campaign}`);
    const hostTalk = page.getByTestId("talk-panel");
    await expect(hostTalk).toBeVisible();
    await talkBox(page).fill("Welcome to the Wayside Inn!");
    await hostTalk.getByTestId("talk").click();
    await expect(miraTalk).toContainText("Welcome to the Wayside Inn!");
    await talkBox(mira).fill("Glad to be here.");
    await miraTalk.getByTestId("talk").click();
    await expect(hostTalk).toContainText("Glad to be here.");
    await expect(hostTalk.locator('img[src*="/api/profiles/"]').first()).toBeVisible();
    await expect.poll(() =>
      hostTalk.locator('img[src*="/api/profiles/"]').first().evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth),
    ).toBeGreaterThan(0);
    await page.screenshot({ path: "e2e/screenshots/table-talk-1280x800.png" });

    // The host starts the session, with Mira here: the DM opens the scene on both screens, the talk stays, and Mira
    // may act. The opening is this spec's one beat; an act of hers would play the fight timeline.spec.ts counts on.
    await page.getByTestId("session-start").click();
    await page.getByTestId("start-confirm").click();
    await expect(mira.getByTestId("story")).toContainText(TAVERN_REPLY, { timeout: 30_000 });
    await expect(page.getByTestId("story")).toContainText(TAVERN_REPLY, { timeout: 30_000 });
    await expect(hostTalk).toContainText("Glad to be here.");
    await composer(mira).fill("Wren pushes open the inn's door.");
    await expect(mira.getByTestId("act")).toBeEnabled();

    // Nothing of the owner's reaches Mira's context.
    for (const path of ["/api/campaigns", "/api/preferences", "/api/connections", `/api/campaigns/${campaign}/dm/log`, "/api/accounts"]) {
      expect((await miraContext.request.get(path)).status(), path).toBe(403);
    }

    // She logs out: the front page (DEL-144), and its Log in the login page.
    await mira.goto("/preferences");
    await mira.getByTestId("account-logout").click();
    await expect(mira).toHaveURL(/\/$/);
    await mira.goto("/login");
    await expect(mira.getByTestId("login-username")).toBeVisible();
    await mira.screenshot({ path: "e2e/screenshots/login-1280x800.png" });
    await miraContext.close();

    // A fresh browser context: the login page, then her table in My tables.
    const freshContext = await browser.newContext({
      viewport: { width: 1280, height: 800 },
      extraHTTPHeaders: { "X-Forwarded-For": "203.0.113.25" },
    });
    await freshContext.addInitScript(tourSeen);
    const fresh = await freshContext.newPage();
    await fresh.goto("/login");
    await fresh.getByTestId("login-username").fill("wren.player");
    await fresh.getByTestId("login-password").fill(PASSWORD);
    await fresh.getByTestId("login-submit").click();
    const row = fresh.getByTestId(`my-table-${campaign}`);
    await expect(row).toContainText("The Wayside Inn");
    await fresh.screenshot({ path: "e2e/screenshots/my-tables-1280x800.png" });
    await fresh.getByTestId(`my-table-play-${campaign}`).click();
    await expect(fresh).toHaveURL(new RegExp(`/play/${campaign}$`));
    const mine = fresh.getByTestId("talk-panel").locator(".talk.mine");
    await expect(mine).toContainText("Glad to be here.");
    await expect(mine.locator(".talk-who")).toHaveText("You");
    await expect(fresh.getByTestId("story")).toContainText(TAVERN_REPLY);
    await expect(fresh.getByTestId("composer")).toBeVisible();
    await expect(fresh.getByTestId("act")).toBeVisible();
    await freshContext.close();
  } finally {
    // So the later specs see what they saw before.
    expect((await request.delete(`/api/campaigns/${campaign}`, json)).status()).toBe(204);
  }
});
