// Voice at the table in two real browsers (table voice and fixes Task V2.3), against `delve serve` with a fake
// `claude`: the host on this machine talks through Chromium's fake microphone (`--use-fake-device-for-media-stream`,
// in playwright.config.ts), and Lark, an account from outside, joins listening only (an init script makes her
// `getUserMedia` refuse). The host's frames reach Lark through Delve's own WebSocket, her screen lights the host's
// mark while the fake microphone beeps, and when the host switches voice off on the campaign page both lose the
// controls. Screenshots in e2e/screenshots/.
//
// It runs after u-fixit.spec.ts and before world.spec.ts (file order). It plays no beat, makes no owner account, and
// makes its own campaign, deleted at the end, so the later specs find what they found before.
import { expect, test, type Page, type WebSocket } from "@playwright/test";

const json = { headers: { "Content-Type": "application/json" } };

/** Counts the binary frames a page's voice socket receives. */
function countRelayed(page: Page): { frames: number } {
  const seen = { frames: 0 };
  page.on("websocket", (socket: WebSocket) => {
    if (!socket.url().endsWith("/voice")) return;
    socket.on("framereceived", ({ payload }) => {
      if (typeof payload !== "string") seen.frames += 1;
    });
  });
  return seen;
}

test("two seats join voice, one listening only, and the frames go through Delve's socket", async ({ page, browser, request }) => {
  const [crypt] = await (await request.get("/api/campaigns")).json();
  const made = await request.post("/api/campaigns", { ...json, data: { name: "The Echoing Vault", module_id: crypt.module_id } });
  expect(made.status(), await made.text()).toBe(201);
  const campaign: string = (await made.json()).id;
  const larkContext = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    extraHTTPHeaders: { "X-Forwarded-For": "203.0.113.31" },
  });
  try {
    const { join_token: token } = await (await request.get(`/api/campaigns/${campaign}/invite`)).json();
    // Lark has no microphone to give.
    await larkContext.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("no microphone", "NotFoundError"));
    });
    const joined = await larkContext.request.post(`/api/join/${token}/account`, {
      ...json,
      data: { username: "lark.listener", password: "correct horse battery", display_name: "Lark", language: "en", role: "player" },
    });
    expect(joined.status(), await joined.text()).toBe(201);
    const larkSeat: string = (await joined.json()).seat.id;
    const seats: { id: string; role: string }[] = await (await request.get(`/api/campaigns/${campaign}/seats`)).json();
    const hostSeat = seats.find((s) => s.role === "host")!.id;

    const lark = await larkContext.newPage();
    const heard = countRelayed(lark);
    await page.goto(`/play/${campaign}`);
    await lark.goto(`/play/${campaign}`);

    // Nothing is asked of anyone until they press Join voice.
    await page.getByTestId("voice-join").click();
    await expect(page.getByTestId("voice-mute")).toBeVisible();
    await lark.getByTestId("voice-join").click();
    await expect(lark.getByTestId("voice-listening-only")).toHaveText("Listening only");
    await expect(lark.getByTestId("voice-mute")).toHaveCount(0);

    // The host's audio reaches Lark through the relay: the fake microphone sends 50 frames a second.
    await expect.poll(() => heard.frames, { timeout: 10_000 }).toBeGreaterThan(0);
    const before = heard.frames;
    await page.waitForTimeout(2000);
    expect(heard.frames - before, "frames relayed to Lark in 2 s").toBeGreaterThan(20);

    // On Lark's screen the host is in voice and lights while the fake microphone beeps; on the host's, Lark listens.
    const hostOnLark = lark.locator(`[data-seat="${hostSeat}"]`);
    await expect(hostOnLark.getByTestId("voice-mark")).toHaveText("In voice");
    await expect(hostOnLark.getByTestId("voice-mark")).toHaveAttribute("data-speaking", "true", { timeout: 10_000 });
    await expect(page.locator(`[data-seat="${larkSeat}"]`).getByTestId("voice-mark")).toHaveText("Listening only");
    await page.screenshot({ path: "e2e/screenshots/voice-desktop.png" });

    // Muted, the host sends nothing more.
    await page.getByTestId("voice-mute").click();
    await expect(hostOnLark.getByTestId("voice-mark")).toHaveText("Muted");
    await page.waitForTimeout(300);
    const muted = heard.frames;
    await page.waitForTimeout(1000);
    expect(heard.frames - muted, "frames after Mute").toBe(0);
    await page.getByTestId("voice-mute").click();
    await expect(hostOnLark.getByTestId("voice-mark")).toHaveText("In voice");

    // On a phone, the controls are on the Table screen, and voice outlived the change of layout.
    await lark.setViewportSize({ width: 390, height: 844 });
    await lark.getByTestId("tab-table").click();
    await expect(lark.getByTestId("phone-screen").getByTestId("voice-listening-only")).toBeVisible();
    await lark.screenshot({ path: "e2e/screenshots/voice-phone.png" });
    await lark.setViewportSize({ width: 1280, height: 800 });

    // The host switches voice off on the campaign page: everyone is out of voice, and the controls go.
    const settings = await page.context().newPage();
    await settings.goto(`/campaigns/${campaign}`);
    const off = settings.getByTestId("table-settings").getByLabel("Off");
    await off.click();
    await expect(off).toBeChecked();
    await expect(page.getByTestId("voice-controls")).toHaveCount(0);
    await expect(lark.getByTestId("voice-controls")).toHaveCount(0);
    await expect(hostOnLark.getByTestId("voice-mark")).toHaveCount(0);
    await settings.close();
  } finally {
    await larkContext.close();
    await page.goto("about:blank");
    // So the later specs see what they saw before.
    expect((await request.delete(`/api/campaigns/${campaign}`, json)).status()).toBe(204);
  }
});
