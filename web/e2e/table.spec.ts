// A table in real browsers, against `delve serve` with a fake `claude` (plan 4 Task 10): the host on this machine, Ana
// who joins by the link in a second browser and plays in Dutch, and Cy who watches on a phone (390x844). Both act, the
// beat closes on Ana's act, the DM tells Pippa something only Ana reads, and Ana reads the reply in Dutch. Screenshots
// in e2e/screenshots/. It runs after play.spec.ts, on its campaign, whose party is Garrek and Pippa.
import { expect, test, type Page } from "@playwright/test";

const told = "Pippa alone hears a voice behind the altar.";

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

test("a table of three: join by the link, act together, a private tell, Dutch, the phone", async ({ page, browser, request }) => {
  const campaigns = await (await request.get("/api/campaigns")).json();
  expect(campaigns).toHaveLength(1);
  const campaign = campaigns[0].id as string;
  const characters = await (await request.get(`/api/campaigns/${campaign}/characters`)).json();
  const pippa = characters.find((c: { name: string }) => c.name === "Pippa").id as string;
  // The invite's URL is for the LAN; this server listens on loopback only, so the browsers use its token here.
  const { join_token: token } = await (await request.get(`/api/campaigns/${campaign}/invite`)).json();

  // The host's play screen, alone at the table: the invite, with its QR code, is open.
  await page.addInitScript(tourSeen);
  await page.goto(`/play/${campaign}`);
  await page.getByTestId("play-aside").getByRole("tab", { name: /^Table/ }).click();
  await expect(page.getByTestId("host-controls")).toBeVisible();
  await expect(page.getByTestId("invite-url")).toHaveValue(new RegExp(`/join/${token}$`));
  await expect(page.getByTestId("invite-qr")).toBeVisible();

  // Ana joins in a browser of her own, in Dutch, and plays Pippa.
  const anaContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await anaContext.addInitScript(tourSeen);
  const ana = await anaContext.newPage();
  await ana.goto(`/join/${token}`);
  // Every invite asks for an account: Ana makes one.
  await ana.getByTestId("join-username").fill("ana");
  await ana.getByTestId("join-password").fill("correct horse battery");
  await ana.getByTestId("join-name").fill("Ana");
  await ana.getByTestId("join-language").selectOption("nl");
  await ana.getByTestId("join-role-player").check();
  await ana.getByTestId("join-submit").click();
  await ana.getByTestId(`join-character-${pippa}`).check();
  await ana.getByTestId("join-play").click();
  await expect(ana).toHaveURL(new RegExp(`/play/${campaign}$`));
  await expect(ana.getByTestId("composer")).toBeVisible();
  await expect(ana.getByTestId("host-controls")).toHaveCount(0);

  // Cy watches on a phone.
  const cyContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await cyContext.addInitScript(tourSeen);
  const cy = await cyContext.newPage();
  await cy.goto(`/join/${token}`);
  await cy.getByTestId("join-username").fill("cy.watch");
  await cy.getByTestId("join-password").fill("correct horse battery");
  await cy.getByTestId("join-name").fill("Cy");
  await cy.getByTestId("join-role-observer").check();
  await expect(cy.getByTestId("join-submit")).toBeEnabled();
  await cy.screenshot({ path: "e2e/screenshots/join-390x844.png" });
  await cy.getByTestId("join-submit").click();
  await expect(cy).toHaveURL(new RegExp(`/play/${campaign}$`));
  await expect(cy.getByTestId("phone-tabs")).toBeVisible();
  await expect(cy.getByTestId("act")).toHaveCount(0);

  // The host acts, and the beat waits for Ana: her indicator says the host has acted.
  const seats = await (await request.get(`/api/campaigns/${campaign}/seats`)).json();
  const host = seats.find((s: { role: string }) => s.role === "host").id as string;
  await composer(page).fill("Garrek keeps his shield up and watches the nave.");
  await composer(page).press("Enter");
  await expect(page.getByTestId("my-act")).toBeVisible();
  await expect(ana.locator(`[data-testid=seat-indicators] li[data-seat="${host}"]`)).toHaveAttribute("data-state", "submitted");
  await expect(page.getByTestId("thinking")).toBeHidden();

  // Ana acts in Dutch: the beat closes, and the DM answers both.
  await composer(ana).fill("Ik open de deur van de kapel.");
  await composer(ana).press("Enter");
  const anaStory = ana.getByTestId("story");
  await expect(anaStory).toContainText(told, { timeout: 30_000 });
  await expect(anaStory.getByTestId("only-you").first()).toBeVisible();
  await expect(anaStory).toContainText("NL: The chapel door creaks open on a dusty nave.", { timeout: 30_000 });
  await expect(anaStory).toContainText("NL: A cold draught comes from the east");
  await expect(anaStory.getByTestId("translating")).toHaveCount(0);

  const hostStory = page.getByTestId("story");
  await expect(hostStory).toContainText("A cold draught comes from the east", { timeout: 30_000 });
  await expect(hostStory).not.toContainText(told);
  await expect(hostStory).not.toContainText("NL:");

  // Table talk, from the host in the talk panel's own box, reaches the others.
  await talkBox(page).fill("Nice work, Pippa.");
  await page.getByTestId("talk-panel").getByTestId("talk").click();
  await expect(ana.getByTestId("talk-panel")).toContainText("NL: Nice work, Pippa.");
  await expect(ana.getByTestId("talk-panel").getByTestId("translating")).toHaveCount(0);
  await expect(page.getByTestId("talk-panel")).toContainText("Nice work, Pippa.");

  await page.screenshot({ path: "e2e/screenshots/table-host-1280x800.png" });
  await ana.screenshot({ path: "e2e/screenshots/table-player-1280x800.png" });

  // The phone: the story and the composer; the observer saw no tell.
  const cyStory = cy.getByTestId("story");
  await expect(cyStory).toContainText("A cold draught comes from the east");
  await expect(cyStory).not.toContainText(told);
  await cy.screenshot({ path: "e2e/screenshots/table-phone-390x844.png" });
  await cy.getByTestId("tab-table").click();
  await expect(cy.getByTestId("phone-screen")).toContainText("Nice work, Pippa.");

  // Delve's own dialog: Ana thinks of leaving, and stays.
  await ana.getByTestId("play-aside").getByRole("tab", { name: /^Tafel/ }).click();
  await ana.locator("button.leave-table").click();
  const dialog = ana.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await ana.screenshot({ path: "e2e/screenshots/dialog-confirm-1280x800.png" });
  await ana.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(ana).toHaveURL(new RegExp(`/play/${campaign}$`));

  await anaContext.close();
  await cyContext.close();
});
