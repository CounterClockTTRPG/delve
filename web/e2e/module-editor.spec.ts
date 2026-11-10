// The module editor in a real browser (plan 3 Task 10), against the same fake server as the play screen: the crypt's
// Text tab, a keyed heading typed at the end of its key, the room chip it gets, Save, a reload and the same text; and
// the NPC form. Screenshots on a laptop (1280x800) in e2e/screenshots/.
import { expect, test, type APIRequestContext } from "@playwright/test";

type Source = { texts: { id: string; markdown: string }[] };

async function cryptKey(request: APIRequestContext, moduleId: string): Promise<string> {
  const source: Source = await (await request.get(`/api/modules/${moduleId}/source`)).json();
  return source.texts.find((text) => text.id === "crypt-key")!.markdown;
}

test("write a keyed heading in the crypt, save, reload; the NPC form", async ({ page, request }) => {
  const modules = await (await request.get("/api/modules")).json();
  expect(modules).toHaveLength(1);
  const moduleId: string = modules[0].id;
  const before = await cryptKey(request, moduleId);

  await page.goto(`/modules/${moduleId}?tab=text`);
  await expect(page.getByRole("tab", { name: "Text" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: /Keyed encounters/ }).click();
  const editor = page.locator(".ProseMirror");
  await expect(page.getByLabel("Linked to the room Entry Hall on crypt")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();

  // Type a keyed heading after the last paragraph. ProseMirror settles its selection a moment after it takes focus.
  await editor.getByText("purse of 40 gp").click();
  await page.waitForTimeout(300);
  // The end of the text: the paragraph wraps, and End alone stops at the end of its visual line.
  await page.keyboard.press("Control+End");
  await page.keyboard.press("Enter");
  await page.keyboard.type("## 4. Vestry");
  await page.keyboard.press("Enter");
  await page.keyboard.type("Behind the robes, a ladder goes up to the bell loft.");

  // Save: the heading links itself to the vestry, and its chip shows the room.
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  const vestry = page.locator(".keyed-heading", { hasText: "4. Vestry" });
  await expect(vestry.getByLabel("Linked to the room Vestry on crypt")).toBeVisible();
  const saved = await cryptKey(request, moduleId);
  expect(saved.startsWith(before.trimEnd())).toBe(true);
  expect(saved).toContain("## 4. Vestry");
  expect(saved).toContain("Behind the robes, a ladder goes up to the bell loft.");
  await vestry.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/module-text-1280x800.png" });

  // Reload: the same text, and the chip again.
  await page.reload();
  await page.getByRole("button", { name: /Keyed encounters/ }).click();
  await expect(editor).toContainText("Behind the robes, a ladder goes up to the bell loft.");
  await expect(page.locator(".keyed-heading", { hasText: "4. Vestry" }).getByLabel("Linked to the room Vestry on crypt")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(await cryptKey(request, moduleId)).toBe(saved);

  // The NPC form: Brother Kael, with his 2e stats.
  await page.getByRole("tab", { name: "NPCs" }).click();
  await page.getByRole("button", { name: /Brother Kael/ }).click();
  await expect(page.locator("#entity-npcs-name")).toHaveValue("Brother Kael");
  await page.screenshot({ path: "e2e/screenshots/module-npc-1280x800.png" });
});

test("a text without keys takes the whole width, with no outline (DEL-121)", async ({ page, request }) => {
  const [module] = await (await request.get("/api/modules")).json();
  const made = await request.post(`/api/modules/${module.id}/texts`, { data: { id: "dm-notes", title: "DM notes" } });
  expect(made.status()).toBe(201);
  await request.put(`/api/modules/${module.id}/texts/dm-notes`, { data: { markdown: "The village fears the old mill.\n" } });

  await page.goto(`/modules/${module.id}?tab=text`);
  await page.getByRole("button", { name: /DM notes/ }).click();
  await expect(page.locator(".ProseMirror")).toContainText("The village fears the old mill.");
  await expect(page.locator(".text-outline")).toHaveCount(0);
  const meta = (await page.locator(".text-meta").boundingBox())!;
  const text = (await page.locator(".text-page").boundingBox())!;
  expect(text.width).toBeGreaterThan(meta.width * 0.95);
  await page.screenshot({ path: "e2e/screenshots/module-text-no-keys-1280x800.png" });
});
