// Crop, turn and split a module's picture (DEL-40) in a real browser: a picture uploaded to the crypt, a box drawn on it
// with the mouse, a turn, Save; the card shows the cut; a split into two; Reset. The pictures are deleted at the end,
// so the later specs see the crypt as it was. A screenshot on a laptop (1280x800) in e2e/screenshots/.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const AVATAR = readFileSync(new URL("./avatar-300x200.png", import.meta.url));

type Attachment = { id: string; sha256: string; cut: { original: string; rotate: number; box: number[] | null } | null };

test("crop, turn and split a picture, then reset it", async ({ page, request }) => {
  const modules: { id: string; title: string }[] = await (await request.get("/api/modules")).json();
  const crypt = modules.find((m) => m.title === "The Crypt of Saint Vellis")!;
  const assets = `/api/modules/${crypt.id}/assets`;
  const uploaded = await request.post(`${assets}?name=crop-plate.png`, {
    data: AVATAR,
    headers: { "Content-Type": "image/png" },
  });
  expect(uploaded.status()).toBe(201);
  const plate: Attachment = await uploaded.json();
  const attachment = async (id: string): Promise<Attachment> =>
    (await (await request.get(`/api/modules/${crypt.id}/source`)).json()).attachments.find((a: Attachment) => a.id === id);

  try {
    await page.goto(`/modules/${crypt.id}`);
    await page.getByRole("tab", { name: "Attachments", exact: true }).click();
    const card = page.locator(".attachment-card", { has: page.getByLabel(`Description of ${plate.id}`, { exact: true }) });
    await card.getByRole("button", { name: `Crop ${plate.id}`, exact: true }).click();
    const dialog = page.getByRole("dialog");
    const stage = dialog.getByTestId("crop-stage");
    await expect(stage.locator("img")).toHaveJSProperty("complete", true);

    // Draw the left half's box with the mouse, then turn: the box turns with the picture.
    const box = (await stage.boundingBox())!;
    await page.mouse.move(box.x + box.width * 0.05, box.y + box.height * 0.1);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.5, { steps: 5 });
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.9, { steps: 5 });
    await page.mouse.up();
    await expect(dialog.getByTestId("crop-box-1")).toBeVisible();
    await dialog.getByRole("button", { name: "Turn right" }).click();
    await page.screenshot({ path: "e2e/screenshots/picture-crop-1280x800.png" });
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog).toBeHidden();

    const cut = await attachment(plate.id);
    expect(cut.cut?.rotate).toBe(90);
    expect(cut.cut?.original).toBe(plate.sha256);
    expect(cut.sha256).not.toBe(plate.sha256);
    const shown = card.locator(".attachment-thumb img");
    await expect(shown).toHaveAttribute("src", `${assets}/${plate.id}?v=${cut.sha256.slice(0, 12)}`);
    // The turned left half: a portrait 160 wide, 120 tall, give or take the mouse's pixels.
    const [width, height] = await shown.evaluate((img: HTMLImageElement) => [img.naturalWidth, img.naturalHeight]);
    expect(width).toBeGreaterThan(130);
    expect(height).toBeGreaterThan(120);
    expect(height).toBeLessThan(170);

    // Split: a second piece, the whole picture, with its own description.
    await card.getByRole("button", { name: `Crop ${plate.id}`, exact: true }).click();
    await dialog.getByRole("button", { name: "Add piece" }).click();
    await dialog.getByLabel("Description of piece 2").fill("The whole plate, turned");
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByLabel(`Description of ${plate.id}-2`)).toHaveValue("The whole plate, turned");

    // Reset: the first is the whole original again; the second piece stays.
    await card.getByRole("button", { name: `Reset the crop of ${plate.id}`, exact: true }).click();
    await expect(card.getByRole("button", { name: `Reset the crop of ${plate.id}`, exact: true })).toBeHidden();
    await expect(shown).toHaveAttribute("src", `${assets}/${plate.id}?v=${plate.sha256.slice(0, 12)}`);
    expect((await attachment(plate.id)).cut).toBeNull();
    expect((await attachment(`${plate.id}-2`)).cut?.rotate).toBe(90);
  } finally {
    for (const id of [plate.id, `${plate.id}-2`]) await request.delete(`${assets}/${id}`, { data: {} });
  }
});
