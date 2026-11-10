// A thorough conversion in a real browser (thorough conversion Task 8), against the same fake server as the play
// screen: the PDF form offers Thorough by default, the conversion's agents are the fake agent
// (tests/fakes/fake_claude_agent.py) and its side calls are answered by their prompt (tests/e2e/fake_play_server.py).
// The fake agent's first cleaning session meets the usage limit: the job pauses at step 5 of 10, says why and when it
// resumes by itself. Resume runs it again, and its second cleaning session is slow: a second book uploaded meanwhile
// waits in the queue (the Conversions panel, owner addition 2026-10-23). Paused by hand, the job stops and the queued
// one starts, which is then cancelled. With the queue paused, Resume only queues the job; unpaused, it runs on to the
// module, with the house's map traced from the book, the ship's sketched, and the doubts list with the cost; Tell the
// DM writes the doubts into the DM-only notes.
//
// It makes a draft module and no campaign, so the carry spec, which carries the party on into the ready module New
// module made, doesn't pick it. Screenshots on a laptop (1280x800) in e2e/screenshots/.
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const python = process.env.DELVE_E2E_PYTHON ?? "uv run python";

test("convert a PDF thoroughly: paused at the usage limit, resumed, its doubts and cost on the module", async ({ page, request }, testInfo) => {
  test.setTimeout(180_000);
  const book = testInfo.outputPath("saltmarsh.pdf");
  execSync(`${python} -m tests.e2e.fake_play_server --thorough-book "${book}"`, { cwd: ".." });

  // The form: Thorough is the default, with its hint; the book-maps checkbox is Quick's alone.
  await page.goto("/modules/new?way=pdf");
  const pdf = page.getByTestId("choice-pdf");
  await expect(pdf.getByLabel("Thorough (default)")).toBeChecked();
  await expect(pdf.getByText("Checks every page, traces every map from the book.")).toBeVisible();
  await expect(pdf.getByLabel("Draw each map from the book's map page")).toHaveCount(0);
  await pdf.getByLabel("The PDF").setInputFiles({ name: "Saltmarsh.pdf", mimeType: "application/pdf", buffer: readFileSync(book) });
  await expect(pdf.getByLabel("Title")).toHaveValue("Saltmarsh");
  await pdf.getByLabel("A draft to work on").check();
  await page.screenshot({ path: "e2e/screenshots/thorough-form-1280x800.png" });
  await pdf.getByRole("button", { name: "Convert" }).click();

  // Paused at the usage limit, in the cleaning: why, when it resumes by itself, the cost so far, Resume.
  const progress = page.getByTestId("conversion-progress");
  await expect(progress).toHaveAttribute("data-status", "paused", { timeout: 60_000 });
  await expect(progress).toContainText("Paused · Step 5 of 10 · Cleaning the texts against the pages");
  await expect(progress).toContainText("The Claude usage limit was reached. It resumes by itself after 3am (UTC)");
  await expect(progress).toContainText("Cost so far: $1.00");
  await page.screenshot({ path: "e2e/screenshots/thorough-paused-1280x800.png" });

  // A reload finds it paused.
  await page.reload();
  await expect(progress).toHaveAttribute("data-status", "paused");
  await progress.getByRole("button", { name: "Resume" }).click();
  await expect(progress).toHaveAttribute("data-status", "running");

  // A second book uploaded while it runs waits in the queue.
  const panel = page.getByTestId("conversions-panel");
  await pdf.getByLabel("The PDF").setInputFiles({ name: "Dunwater.pdf", mimeType: "application/pdf", buffer: readFileSync(book) });
  await pdf.getByLabel("Title").fill("Dunwater");
  await pdf.getByLabel("A draft to work on").check();
  await pdf.getByRole("button", { name: "Convert" }).click();
  await expect(progress).toHaveAttribute("data-status", "queued");
  const queue = panel.getByRole("list", { name: "The conversion queue" });
  const saltmarsh = queue.getByRole("listitem").filter({ hasText: "Saltmarsh" });
  const dunwater = queue.getByRole("listitem").filter({ hasText: "Dunwater" });
  await expect(saltmarsh).toHaveAttribute("data-status", "running");
  await expect(saltmarsh).toContainText("Step 5 of 10 · Cleaning the texts against the pages");
  await expect(dunwater).toHaveAttribute("data-status", "queued");
  await expect(dunwater).toContainText("Number 1 in the queue");
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/conversions-queue-1280x800.png" });

  // Paused by hand: its agent stops, and the queued book starts.
  await saltmarsh.getByRole("button", { name: "Pause" }).click();
  await expect(saltmarsh).toHaveAttribute("data-status", "paused");
  await expect(saltmarsh).toContainText("You paused it.");
  await expect(saltmarsh).toContainText("Cost so far: $1.00");
  await expect(dunwater).toHaveAttribute("data-status", "running");
  await page.screenshot({ path: "e2e/screenshots/conversions-paused-1280x800.png" });
  await dunwater.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Cancel and delete the work" }).click();
  await expect(dunwater).toHaveCount(0);

  // The queue paused: Resume puts the job in the queue, and nothing starts until the queue is unpaused.
  await panel.getByRole("button", { name: "Pause the queue" }).click();
  await expect(panel).toContainText("The queue is paused: no waiting conversion starts");
  await saltmarsh.getByRole("button", { name: "Resume" }).click();
  await expect(saltmarsh).toHaveAttribute("data-status", "queued");
  await page.screenshot({ path: "e2e/screenshots/conversions-queue-paused-1280x800.png" });
  const queued: { status: string }[] = (await (await request.get("/api/conversions/queue")).json()).jobs;
  expect(queued.map((j) => j.status)).toEqual(["queued"]);
  await panel.getByRole("button", { name: "Unpause the queue" }).click();

  // It runs on from the cleaning, to the module.
  await page.reload();
  await expect(progress.getByRole("link", { name: "Open the module" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Cost: $3.00")).toBeVisible();
  await progress.getByRole("link", { name: "Open the module" }).click();

  // The module: the house's map traced from the book, the ship's sketched; the doubts and the cost.
  await expect(page.getByRole("heading", { level: 1, name: "Saltmarsh" })).toBeVisible();
  const doubts = page.getByTestId("conversion-doubts");
  await expect(doubts.getByRole("heading", { name: /Doubts from the conversion/ })).toContainText("Cost: $3.00");
  await expect(doubts).toContainText("Flagged by the text check");
  await expect(doubts).toContainText("Key 3 covers 80%: the layer runs on.");
  await expect(doubts).toContainText("Sketched map");
  await expect(doubts).toContainText("Picture placed without confidence");
  await expect(doubts.getByRole("link", { name: "2" }).first()).toHaveAttribute("href", /\/assets\/source-pdf#page=2$/);
  await doubts.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "e2e/screenshots/thorough-doubts-1280x800.png" });

  const conversions: { id: string; title: string; module_id: string | null; status: string }[] = await (
    await request.get("/api/conversions")
  ).json();
  const job = conversions.find((c) => c.title === "Saltmarsh")!;
  expect(job.status).toBe("done");
  const module: { maps: { name: string; source: string }[] } = await (await request.get(`/api/modules/${job.module_id}`)).json();
  const maps = Object.fromEntries(module.maps.map((m) => [m.name, m.source]));
  expect(Object.keys(maps)).toEqual(["house", "ship"]);
  expect(maps.house).toContain('room "r1"');
  expect(maps.house.startsWith("# Sketched")).toBe(false);
  expect(maps.ship.startsWith("# Sketched from the room key")).toBe(true);

  // Tell the DM: the doubts go into the DM-only notes.
  await doubts.getByRole("button", { name: "Tell the DM" }).click();
  await expect(doubts.getByRole("status")).toContainText("Told the DM");
  const source: { texts: { id: string; markdown: string }[] } = await (await request.get(`/api/modules/${job.module_id}/source`)).json();
  expect(source.texts.find((t) => t.id === "making-notes")?.markdown).toContain("## Doubts from the conversion");
});
