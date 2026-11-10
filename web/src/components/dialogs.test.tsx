import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import EntityForm from "../module/EntityForm";
import { DialogsProvider, useConfirm, usePrompt } from "./dialogs";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** A button that opens a confirm or a prompt and shows what it answered. */
function Opener({ kind }: { kind: "confirm" | "prompt" }) {
  const confirm = useConfirm();
  const prompt = usePrompt();
  const [answer, setAnswer] = useState("none");
  async function open() {
    const result =
      kind === "confirm"
        ? await confirm({ title: "Delete the map crypt?", body: "It can't be undone.", confirm: "Delete", danger: true })
        : await prompt({ title: "A new text", label: "Title", initial: "Vestry", confirm: "Make it" });
    setAnswer(JSON.stringify(result));
  }
  return (
    <>
      <button type="button" onClick={open}>
        Open
      </button>
      <output>{answer}</output>
    </>
  );
}

function renderOpener(kind: "confirm" | "prompt") {
  render(
    <I18nProvider language="en">
      <DialogsProvider>
        <Opener kind={kind} />
      </DialogsProvider>
    </I18nProvider>,
  );
  const opener = screen.getByRole("button", { name: "Open" });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

const answer = () => screen.getByRole("status").textContent;

describe("useConfirm", () => {
  it("answers true when confirmed", async () => {
    renderOpener("confirm");
    const dialog = await screen.findByRole("alertdialog", { name: "Delete the map crypt?" });
    expect(dialog.textContent).toContain("It can't be undone.");
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(answer()).toBe("true"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("answers false when cancelled", async () => {
    renderOpener("confirm");
    await screen.findByRole("alertdialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(answer()).toBe("false"));
  });

  it("answers false on Escape", async () => {
    renderOpener("confirm");
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(answer()).toBe("false"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("has a red button for a danger confirm", async () => {
    renderOpener("confirm");
    await screen.findByRole("alertdialog");
    expect(screen.getByRole("button", { name: "Delete" }).className).toContain("danger");
  });

  it("gives the focus back to the opener", async () => {
    const opener = renderOpener("confirm");
    await screen.findByRole("alertdialog");
    expect(document.activeElement).not.toBe(opener);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});

describe("usePrompt", () => {
  it("answers the text typed", async () => {
    renderOpener("prompt");
    await screen.findByRole("dialog", { name: "A new text" });
    const input = screen.getByLabelText("Title") as HTMLInputElement;
    expect(input.value).toBe("Vestry");
    fireEvent.change(input, { target: { value: "The Vestry" } });
    fireEvent.click(screen.getByRole("button", { name: "Make it" }));
    await waitFor(() => expect(answer()).toBe('"The Vestry"'));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("answers the text on Enter", async () => {
    renderOpener("prompt");
    const input = (await screen.findByLabelText("Title")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Ossuary" } });
    fireEvent.submit(input.form!);
    await waitFor(() => expect(answer()).toBe('"Ossuary"'));
  });

  it("answers null when cancelled", async () => {
    renderOpener("prompt");
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(answer()).toBe("null"));
  });

  it("answers null on Escape, and gives the focus back", async () => {
    const opener = renderOpener("prompt");
    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(answer()).toBe("null"));
    await waitFor(() => expect(document.activeElement).toBe(opener));
  });
});

describe("a delete call site", () => {
  it("asks with a danger confirm, and deletes nothing when cancelled", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <I18nProvider language="en">
          <DialogsProvider>
            <EntityForm
              moduleId="mod_cccccccccccc"
              kind="npcs"
              record={{ id: "grik", name: "Grik" }}
              source={{ texts: [], entities: { npcs: [{ id: "grik", name: "Grik" }] }, attachments: [], keys: [], links: [], warnings: [] }}
              onSaved={vi.fn()}
              onDeleted={vi.fn()}
            />
          </DialogsProvider>
        </I18nProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete Grik?" });
    const confirm = [...dialog.querySelectorAll("button")].find((b) => b.textContent === "Delete")!;
    expect(confirm.className).toContain("danger");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

// Tests run in web/.
const SRC = join(process.cwd(), "src");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : [];
  });
}

describe("the browser's own dialogs", () => {
  it("are used nowhere in web/src outside tests", () => {
    const files = sourceFiles(SRC);
    expect(files.length).toBeGreaterThan(20);
    const left = files.filter((path) => /window\.(confirm|prompt)\b/.test(readFileSync(path, "utf8")));
    expect(left.map((path) => path.slice(SRC.length + 1))).toEqual([]);
  });
});
