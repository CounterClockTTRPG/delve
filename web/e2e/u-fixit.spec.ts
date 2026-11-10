// Fix-it comments in a real browser (table voice and fixes Task F2.4), against `delve serve` with a fake `claude`
// (tests/e2e/fake_play_server.py), whose fix-it job (tests/e2e/fake_fixit.py) adds the exit the comment names to the
// module's map. On New module's ready module, The Sunken Shrine (not the crypt, which the module editor's spec expects
// alone and unchanged): a comment on its map, the job followed to "Ready to review", the review with the map before
// and after (on a laptop and a phone), Keep, and the module one revision on, its map holding the exit. Nothing is
// saved before Keep. Screenshots in e2e/screenshots/.
//
// It runs after timeline.spec.ts and before voice.spec.ts (file order). It makes no campaign, so the carry spec still
// carries the party into this module, at its new revision.
import { expect, test } from "@playwright/test";

const COMMENT = "The exit from room 3 to the mill pond is not yet in place, fix it.";

type Module = { id: string; title: string; draft: boolean; head_revision: number | null; maps: { name: string; source: string; is_default: boolean }[] };

test("a fix-it comment, run by the job and kept as a new revision", async ({ page, request }) => {
  const modules: Module[] = await (await request.get("/api/modules")).json();
  const listed = modules.find((m) => m.title === "The Sunken Shrine" && !m.draft);
  expect(listed, "New module's spec makes The Sunken Shrine and marks it ready").toBeDefined();
  const before: Module = await (await request.get(`/api/modules/${listed!.id}`)).json();
  const map = before.maps.find((m) => m.is_default) ?? before.maps[0];
  expect(map.source).not.toContain("exit at");

  await page.goto(`/modules/${before.id}`);
  const fixits = page.getByTestId("fixits");
  await expect(fixits.getByRole("heading", { name: "Fix-it comments" })).toBeVisible();
  await fixits.getByLabel("What should be fixed").fill(COMMENT);
  await fixits.getByLabel("About (optional)").selectOption(`map:${map.name}`);
  await fixits.getByRole("button", { name: "Send" }).click();

  // The job runs in the background, and the comment waits for review; nothing is saved yet.
  const row = fixits.getByTestId("fixit-comment").filter({ hasText: COMMENT });
  await expect(row).toHaveAttribute("data-status", "review", { timeout: 60_000 });
  await expect(row).toContainText("Ready to review");
  await expect(row).toContainText(`the map ${map.name}`);
  const waiting: Module = await (await request.get(`/api/modules/${before.id}`)).json();
  expect(waiting.head_revision).toBe(before.head_revision);
  expect(waiting.maps.find((m) => m.name === map.name)!.source).not.toContain("exit at");

  // The review: the map before and after, the exit drawn only after.
  await row.getByRole("button", { name: "Review" }).click();
  const review = page.getByTestId("fixit-review");
  await expect(review.getByText("Added the exit from room 3 to the mill pond.")).toBeVisible();
  const after = review.getByTestId("fixit-map-after");
  await expect(after.locator("svg [data-exit-to]").first()).toBeAttached();
  await expect(review.getByTestId("fixit-map-before").locator("svg[data-name]")).toBeVisible();
  await expect(review.getByTestId("fixit-map-before").locator("svg [data-exit-to]")).toHaveCount(0);
  await page.screenshot({ path: "e2e/screenshots/fixit-review.png" });

  // On a phone the review is the whole screen, before above after.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(review.getByTestId("fixit-map-before").locator("..")).toHaveAttribute("data-layout", "stacked");
  await page.screenshot({ path: "e2e/screenshots/fixit-phone.png" });
  await page.setViewportSize({ width: 1280, height: 800 });

  // Keep: a new revision, one after the module's, and its map holds the exit.
  const revision = (before.head_revision ?? 0) + 1;
  await review.getByRole("button", { name: "Keep" }).click();
  await expect(review.getByText(`Kept as revision ${revision}`)).toBeVisible();
  await review.getByRole("button", { name: "Close" }).click();
  await expect(row).toHaveAttribute("data-status", "kept");
  await expect(row).toContainText(`Kept as revision ${revision}`);
  const kept: Module = await (await request.get(`/api/modules/${before.id}`)).json();
  expect(kept.head_revision).toBe(revision);
  expect(kept.maps.find((m) => m.name === map.name)!.source).toContain('exit at 11,9 { to "mill pond"');
});
