// Cloud storage in a real browser (cloud storage plan, DEL-110), against `delve serve` with a fake `claude`: the owner
// sets a backup store and a library store, backs up now and sees the run's failures, reads the Restore list, publishes
// the crypt to the library, downloads it, publishes a second version, and takes the update on the downloaded copy;
// then the library with the read right. Screenshots in e2e/screenshots/.
//
// The stores are folders, never a cloud (tests/e2e/fake_play_server.py, `--stores`): `backups` refuses the settings'
// objects, so the run fails in part, and `library-read` is the library's folder again, read only. No credential exists.
// It runs last by file order, plays no beat and makes no owner account; it removes both stores at the end, and puts
// the crypt's title back.
import { expect, test, type APIRequestContext } from "@playwright/test";
import { join } from "node:path";

const CRYPT = "The Crypt of Saint Vellis";
const REVISED = "The Crypt of Saint Vellis, revised";
const OURS = "The Crypt of Saint Vellis, our table's";
const AUTHOR = "The Saint Vellis Society";
const STORES = process.env.DELVE_E2E_STORES!;
const JSON_HEADERS = { "Content-Type": "application/json" };

type Module = { id: string; title: string; library?: { key: string; origin: string; version: number; newer: number | null } | null };

async function modules(request: APIRequestContext): Promise<Module[]> {
  return (await request.get("/api/modules")).json();
}

async function rename(request: APIRequestContext, id: string, title: string) {
  expect((await request.patch(`/api/modules/${id}`, { data: { title }, headers: JSON_HEADERS })).ok()).toBe(true);
}

async function setStore(request: APIRequestContext, kind: "backup" | "library", folder: string) {
  const answer = await request.put(`/api/storage/${kind}`, {
    data: { provider: "local", root: join(STORES, folder) },
    headers: JSON_HEADERS,
  });
  expect(answer.status(), await answer.text()).toBe(200);
}

test("the Storage section, a backup that failed in part, the Restore list, and the library", async ({ page, request }) => {
  expect(STORES).toBeTruthy();
  const crypt = (await modules(request)).find((m) => m.title === CRYPT)!;
  expect(crypt).toBeTruthy();
  await setStore(request, "backup", "backups");
  await setStore(request, "library", "library");

  // Both stores set; Back up now; the backups' folder refuses the settings, so the run is partial and says what failed.
  await page.goto("/preferences");
  const storage = page.getByRole("region", { name: "Storage" });
  await expect(storage.getByRole("group", { name: "Backup store" })).toContainText(join(STORES, "backups"));
  await expect(storage.getByRole("group", { name: "Library store" })).toContainText("Right: Manage");
  await expect(storage.getByText("No backup has run yet.")).toBeVisible();
  await storage.getByRole("button", { name: "Back up now" }).click();
  const lastRun = storage.getByRole("region", { name: "Last backup" });
  await expect(lastRun).toContainText("Partly backed up on", { timeout: 60_000 });
  await expect(lastRun.locator(".run-failures li").first()).toContainText("(Setting): The store refused the write.");
  await expect(storage.getByRole("button", { name: "Back up now" })).toBeEnabled();
  await storage.screenshot({ path: "e2e/screenshots/storage-both-stores-partial-1280x800.png" });

  // The Restore list: this install's backups, the crypt's module and campaign on this install; the setting that
  // failed isn't in it.
  const restore = storage.getByRole("region", { name: "Restore" });
  await expect(restore.getByLabel("Backups of")).toContainText("(this install)");
  await expect(restore.getByRole("checkbox", { name: CRYPT }).first()).toBeVisible();
  await expect(restore.locator(".restore-items")).toContainText("Campaign");
  await expect(restore.locator(".restore-items")).not.toContainText("Setting");
  await expect(restore.getByRole("button", { name: "Restore selected" })).toBeDisabled();
  await restore.scrollIntoViewIfNeeded();
  await restore.screenshot({ path: "e2e/screenshots/storage-restore-list-1280x800.png" });

  // Publish the crypt from the Library tab: the entry is shown before it is made.
  await page.goto("/modules?view=library");
  await expect(page.getByText("The library has no modules yet.")).toBeVisible();
  await page.getByRole("button", { name: "Publish a module…" }).click();
  const publish = page.getByRole("dialog", { name: "Publish to the library" });
  await publish.getByLabel("Module").selectOption(crypt.id);
  await expect(publish.locator(".library-entry")).toContainText(CRYPT);
  await publish.getByLabel("Author").fill(AUTHOR);
  await publish.getByRole("button", { name: "Publish" }).click();
  await expect(publish).toBeHidden();
  const row = page.locator(".library-entries tbody tr", { hasText: CRYPT });
  await expect(row).toContainText(AUTHOR);
  await expect(row).toContainText("Published from here");

  // Download it (the tab offers no Download for an entry this install published), edit the copy, and publish a second
  // version of the crypt: the copy has an update.
  const key = (await modules(request)).find((m) => m.id === crypt.id)!.library!.key;
  const download = await request.post("/api/library/download", { data: { key }, headers: JSON_HEADERS });
  expect(download.status(), await download.text()).toBe(200);
  const copy: Module = await download.json();
  await rename(request, copy.id, OURS);
  await rename(request, crypt.id, REVISED);
  const second = await request.post(`/api/modules/${crypt.id}/publish`, { data: {}, headers: JSON_HEADERS });
  expect(second.status(), await second.text()).toBe(200);
  expect((await second.json()).version).toBe(2);

  // The Library tab with the manage right: publish, new version and delete.
  await page.goto("/modules?view=library");
  await expect(row).toContainText(REVISED);
  await expect(row).toContainText("2");
  await expect(page.getByRole("button", { name: "Publish a module…" })).toBeVisible();
  await expect(page.getByRole("button", { name: `Delete ${REVISED} from the library` })).toBeVisible();
  await expect(page.getByText("This library is read-only here.")).toHaveCount(0);
  await page.screenshot({ path: "e2e/screenshots/library-manage-1280x800.png" });

  // The copy's Update: it was edited here, so the dialog warns and offers to keep it.
  await page.goto(`/modules/${copy.id}`);
  const bar = page.locator(".library-bar");
  await expect(bar).toContainText("Update available");
  await expect(bar).toContainText("Version 2 is in the library.");
  await bar.getByRole("button", { name: "Update" }).click();
  const update = page.getByRole("dialog", { name: `Update ${OURS} to version 2?` });
  await expect(update).toContainText("Your edits to this module will be replaced.");
  await expect(update.getByRole("checkbox", { name: "Keep my version as a separate module" })).toBeChecked();
  await page.screenshot({ path: "e2e/screenshots/library-update-dialog-1280x800.png" });
  await update.getByRole("button", { name: "Update" }).click();
  await expect(update).toBeHidden();
  await expect(bar).toContainText("Updated to version 2");
  const after = await modules(request);
  expect(after.find((m) => m.id === copy.id)!.title).toBe(REVISED);
  expect(after.some((m) => m.title === `${OURS} (my version)`)).toBe(true);

  // The same library, read only: no publish, no delete, and it says so.
  await setStore(request, "library", "library-read");
  await page.goto("/preferences");
  await expect(page.getByRole("group", { name: "Library store" })).toContainText("Right: Read");
  await page.goto("/modules?view=library");
  await expect(row).toContainText(REVISED);
  await expect(page.getByText("This library is read-only here.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish a module…" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Delete / })).toHaveCount(0);
  await page.screenshot({ path: "e2e/screenshots/library-read-1280x800.png" });

  // Leave the install as it was: no stores, the crypt's own title.
  for (const kind of ["backup", "library"]) {
    expect((await request.delete(`/api/storage/${kind}`, { headers: JSON_HEADERS })).ok()).toBe(true);
  }
  await rename(request, crypt.id, CRYPT);
});
