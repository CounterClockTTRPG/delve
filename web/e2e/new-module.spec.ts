// New module and the whole module in print, in a real browser (plan 5 Task 8), against the same fake server as the
// play screen: a PDF converts as a draft, its progress shows during the conversion and after a reload, the module
// opens with its warnings and is marked ready, and its print page lists its parts. The fake answers the conversion's
// side calls by their prompt (tests/e2e/fake_play_server.py). Screenshots on a laptop (1280x800) in e2e/screenshots/.
//
// It makes a module but no campaign: the play screen's spec, which runs after it, finds the crypt's campaign alone.
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const python = process.env.DELVE_E2E_PYTHON ?? "uv run python";

test("convert a PDF as a draft, follow it, open it, mark it ready, print it", async ({ page, request }, testInfo) => {
  const book = testInfo.outputPath("the-sunken-shrine.pdf");
  execSync(`${python} -m tests.e2e.fake_play_server --book "${book}"`, { cwd: ".." });

  await page.goto("/modules/new");
  await expect(page.getByRole("heading", { level: 1, name: "New module" })).toBeVisible();
  // The four ways as cards; the picked one shows only its own form.
  for (const way of ["An empty module", "Import a .dscn", "From a PDF", "Describe the module you want"]) {
    await expect(page.getByRole("button", { name: new RegExp(`^${way.replace(".", "\\.")}`) })).toBeVisible();
  }
  await page.getByRole("button", { name: /^From a PDF/ }).click();
  await expect(page).toHaveURL(/way=pdf/);

  // The PDF, as a draft. Its title comes from the file's name.
  const pdf = page.getByTestId("choice-pdf");
  await pdf.getByLabel("The PDF").setInputFiles({
    name: "The Sunken Shrine.pdf",
    mimeType: "application/pdf",
    buffer: readFileSync(book),
  });
  await expect(pdf.getByLabel("Title")).toHaveValue("The Sunken Shrine");
  // Thorough is the default (the fake `claude` is the Claude CLI); this book goes the quick way.
  await expect(pdf.getByLabel("Thorough (default)")).toBeChecked();
  await pdf.getByLabel("Quick").check();
  await pdf.getByLabel("A draft to work on").check();
  await pdf.getByRole("button", { name: "Convert" }).click();

  // During the conversion: the step, pages done out of pages, and Cancel. Convert stays: a book uploaded now waits in
  // the queue, as the page says (docs/conversions.md, the queue).
  const progress = page.getByTestId("conversion-progress");
  await expect(progress).toHaveAttribute("data-status", "running");
  await expect(progress).toContainText("Converting the text");
  await expect(progress).toContainText("0 of 2 pages");
  await expect(progress.getByRole("button", { name: "Cancel" })).toBeVisible();
  await expect(pdf.getByRole("button", { name: "Convert" })).toBeEnabled();
  await expect(page.getByText("a book you upload or a module you describe now waits in the queue")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/new-module-1280x800.png" });

  // A reload shows the same conversion, still running.
  await page.reload();
  await expect(progress).toHaveAttribute("data-status", "running");
  await expect(progress).toContainText("The Sunken Shrine");

  // After it: done, with its warnings, and the link to the module.
  await expect(progress).toHaveAttribute("data-status", "done", { timeout: 60_000 });
  await expect(progress).toContainText(/Done, with \d+ warnings\./);
  await page.screenshot({ path: "e2e/screenshots/new-module-done-1280x800.png" });

  // The module opens as a draft, with the conversion's warnings; Mark as ready.
  await progress.getByRole("link", { name: "Open the module" }).click();
  await expect(page).toHaveURL(/\/modules\/[^/]+$/);
  const moduleId = decodeURIComponent(page.url().split("/").pop()!);
  await expect(page.getByText("Converted, with these warnings:")).toBeVisible();
  await page.getByText("Converted, with these warnings:").click(); // the warnings are collapsed to one line
  await expect(page.getByText("Sketched from the room key: an invented layout; compare it with page 2.")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/module-converted-1280x800.png" });
  await page.getByRole("tab", { name: "Maps" }).click();
  await expect(page.getByText("Sketched from the room key: the layout is invented.")).toBeVisible();
  await page.screenshot({ path: "e2e/screenshots/module-maps-sketched-1280x800.png" });
  await page.getByRole("button", { name: "Mark as ready" }).click();
  await expect(page.getByRole("button", { name: "Mark as ready" })).toHaveCount(0);
  expect((await (await request.get(`/api/modules/${moduleId}`)).json()).draft).toBe(false);

  // The whole module in print: the title page, the text, the sketched map with its key, the NPCs, the encounters
  // and the images, in that order.
  await page.goto(`/modules/${moduleId}/print`);
  await expect(page.getByRole("heading", { level: 1, name: "The Sunken Shrine", exact: true })).toBeVisible();
  const parts = page.locator("[data-part]");
  await expect(parts).toHaveCount(6);
  expect(await parts.evaluateAll((els) => els.map((el) => el.getAttribute("data-part")))).toEqual([
    "title",
    "text",
    "map",
    "npcs",
    "encounters",
    "images",
  ]);
  const map = page.locator('[data-part="map"]');
  await expect(map.locator("svg").first()).toBeVisible();
  await expect(map).toContainText("Hall of Echoes");
  const text = page.locator('[data-part="text"]');
  await expect(text).toContainText("Every footstep rings back three times.");
  // The chapter is named once: by its own heading, not again by the part's.
  await expect(text.getByRole("heading", { name: /The Sunken Shrine of the Drowned God/ })).toHaveCount(1);
  await expect(page.locator('[data-part="npcs"]')).toContainText("Chief Muckfoot");
  await expect(page.locator('[data-part="images"]')).toContainText("Page 2: a map or full-page picture");
  await page.screenshot({ path: "e2e/screenshots/module-print-1280x800.png" });
});
