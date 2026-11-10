import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Editor } from "@tiptap/core";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createRef } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModuleTextDoc, RoomLink, SourceWarning } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { toMarkdown } from "./MarkdownRoundTrip";
import TextEditor, { MARKDOWN_AFTER_MS, type TextEditorHandle } from "./TextEditor";

vi.mock("./MarkdownRoundTrip", async (original) => {
  const real = await original<typeof import("./MarkdownRoundTrip")>();
  return { ...real, toMarkdown: vi.fn(real.toMarkdown) };
});

const MODULE = "mod_0123456789ab";
const KEYED = "## C1. Entry Hall {#c1}\n\nThe door grinds open.\n";

const text = (markdown: string): ModuleTextDoc => ({ id: "crypt-key", title: "Keyed encounters", audience: "gm", map: "crypt", markdown });
const link: RoomLink = {
  text_id: "crypt-key",
  anchor: "c1",
  key: "C1",
  map: "crypt",
  node: "room.entry_hall",
  label: "Entry Hall",
  explicit: false,
};

let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
    const body = JSON.parse(String(init?.body ?? "{}"));
    return json(200, { text: { ...text(body.markdown ?? ""), ...body }, links: [link], warnings: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderEditor({
  markdown = KEYED,
  links = [link],
  warnings = [],
  onSaved = vi.fn(),
}: { markdown?: string; links?: RoomLink[]; warnings?: SourceWarning[]; onSaved?: ReturnType<typeof vi.fn> } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const handle = createRef<TextEditorHandle>();
  const element = (
    <TextEditor
      ref={handle}
      moduleId={MODULE}
      text={text(markdown)}
      links={links}
      warnings={warnings}
      attachments={[
        { id: "ritualist-token", type: "image/png", sha256: "ab", size: 79, description: "The ritualist", audience: "player" },
        { id: "crypt-plan", type: "application/pdf", sha256: "cd", size: 99, description: "The crypt's plan", audience: "gm" },
      ]}
      entities={{ npcs: [{ id: "ritualist", name: "Cult ritualist" }] }}
      maps={["crypt"]}
      onSaved={onSaved}
    />
  );
  const router = createMemoryRouter(
    [
      { path: "/modules/:moduleId", element },
      { path: "/elsewhere", element: <h1>Elsewhere</h1> },
    ],
    { initialEntries: [`/modules/${MODULE}`] },
  );
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <RouterProvider router={router} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { router, onSaved, handle };
}

/** TipTap hangs the editor on its element. */
async function editorOf(): Promise<Editor> {
  const dom = await waitFor(() => {
    const el = document.querySelector(".ProseMirror") as (HTMLElement & { editor?: Editor }) | null;
    expect(el?.editor).toBeTruthy();
    return el!;
  });
  return dom.editor!;
}

function puts() {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
}

describe("TextEditor", () => {
  it("shows the text finished, never its Markdown", async () => {
    renderEditor({ markdown: "## C2. Throne Room {#c2}\n\n> Runes glow.\n\n[[npc:ritualist]] chants.\n\n![The token](asset:ritualist-token)\n" });
    await editorOf();
    expect(screen.queryByText(/\{#c2\}/)).toBeNull();
    expect(document.querySelector("blockquote.read-aloud")?.textContent).toBe("Runes glow.");
    expect(await screen.findByText("Cult ritualist")).toBeTruthy();
    const image = document.querySelector(".ProseMirror img:not(.ProseMirror-separator)") as HTMLImageElement;
    expect(image.getAttribute("src")).toBe(`/api/modules/${MODULE}/assets/ritualist-token`);
    expect(image.getAttribute("alt")).toBe("The token");
  });

  it("has an outline of its keyed headings, filtered by a search, that puts the cursor on one (G3, E-b)", async () => {
    renderEditor({
      markdown:
        "# The House\n\nIntro.\n\n## 6. Kitchen\n\nPots.\n\n## 7. Dining Room\n\nA long table.\n\n" +
        "## Wandering Monsters\n\nRats.\n\n### 7a. Pantry\n\nJars.\n",
    });
    const editor = await editorOf();
    const outline = screen.getByRole("navigation", { name: "Keys" });
    const entries = () => within(outline).getAllByRole("button").map((b) => b.textContent);
    expect(entries()).toEqual(["6. Kitchen", "7. Dining Room", "7a. Pantry"]);

    fireEvent.change(within(outline).getByRole("searchbox", { name: "Find a key" }), { target: { value: "din" } });
    expect(entries()).toEqual(["7. Dining Room"]);
    fireEvent.change(within(outline).getByRole("searchbox", { name: "Find a key" }), { target: { value: "7" } });
    expect(entries()).toEqual(["7. Dining Room", "7a. Pantry"]);

    fireEvent.click(within(outline).getByRole("button", { name: "7. Dining Room" }));
    const { $from } = editor.state.selection;
    expect($from.parent.type.name).toBe("heading");
    expect($from.parent.textContent).toBe("7. Dining Room");
    // Nothing changed: there is nothing to save.
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows no outline for a text without keys", async () => {
    renderEditor({ markdown: "## Background\n\nLore.\n" });
    await editorOf();
    expect(screen.queryByRole("navigation", { name: "Keys" })).toBeNull();
  });

  it("boxes every quote under a keyed heading, and only the leading ones under another", async () => {
    renderEditor({
      markdown:
        "## C2. Throne Room {#c2}\n\n> Runes glow.\n\nThe ritualist chants.\n\n> The floor shakes.\n\n" +
        "## Background\n\n> Built by monks.\n\nLore.\n\n> A note.\n",
    });
    await editorOf();
    const quotes = Array.from(document.querySelectorAll(".ProseMirror blockquote"));
    expect(quotes.map((q) => [q.textContent, q.classList.contains("read-aloud")])).toEqual([
      ["Runes glow.", true],
      ["The floor shakes.", true],
      ["Built by monks.", true],
      ["A note.", false],
    ]);
  });

  it("makes a read-aloud blockquote with the toolbar's quote", async () => {
    const { onSaved } = renderEditor();
    const editor = await editorOf();
    act(() => {
      editor.commands.focus("end");
    });
    fireEvent.click(screen.getByRole("button", { name: "Read-aloud" }));
    await waitFor(() => expect(document.querySelector("blockquote.read-aloud")?.textContent).toBe("The door grinds open."));

    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(JSON.parse(String(puts()[0][1].body)).markdown).toBe("## C1. Entry Hall {#c1}\n\n> The door grinds open.\n");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("shows a linked heading's room chip, and a heading without a room as a warning", async () => {
    renderEditor({
      markdown: "## C1. Entry Hall {#c1}\n\n## C9. Nowhere\n",
      warnings: [
        {
          code: "key-without-room",
          message: "The heading “C9. Nowhere” in Keyed encounters has no room on the map.",
          ref: "text:crypt-key#c9",
        },
        { code: "key-without-room", message: "Someone else's.", ref: "text:intro#x1" },
      ],
    });
    expect(await screen.findByLabelText("Linked to the room Entry Hall on crypt")).toBeTruthy();
    expect(await screen.findByLabelText("No room on the map for C9")).toBeTruthy();
    // The text's warnings are listed under the editor; another text's are not.
    expect(screen.getByText("The heading “C9. Nowhere” in Keyed encounters has no room on the map.")).toBeTruthy();
    expect(screen.queryByText("Someone else's.")).toBeNull();
  });

  it("writes the Markdown once typing pauses, not on every keystroke; the outline and the save button at once (DEL-172)", async () => {
    renderEditor();
    const editor = await editorOf();
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    const written = vi.mocked(toMarkdown);
    written.mockClear();
    for (const word of [" It", " is", " cold."])
      act(() => {
        editor.chain().focus("end").insertContent(word).run();
      });
    // Unsaved work at once, before its Markdown is written.
    expect(save.disabled).toBe(false);
    expect(written).not.toHaveBeenCalled();
    await act(() => new Promise((resolve) => setTimeout(resolve, MARKDOWN_AFTER_MS + 50)));
    expect(written).toHaveBeenCalledTimes(1);
    // A heading typed shows in the outline without waiting for the Markdown.
    act(() => {
      editor.chain().focus("end").insertContent({ type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "C2. Crypt" }] }).run();
    });
    expect(screen.getByRole("navigation", { name: "Keys" }).textContent).toContain("C2. Crypt");
  });

  it("saves the Markdown with PUT, only once it has changed", async () => {
    const { onSaved } = renderEditor();
    const editor = await editorOf();
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    act(() => {
      editor.chain().focus("end").insertContent(" It is cold.").run();
    });
    await waitFor(() => expect(save.disabled).toBe(false));
    fireEvent.click(save);
    await waitFor(() => expect(puts()).toHaveLength(1));
    const [path, init] = puts()[0];
    expect(path).toBe(`/api/modules/${MODULE}/texts/crypt-key`);
    expect(JSON.parse(String(init.body))).toEqual({
      title: "Keyed encounters",
      audience: "gm",
      map: "crypt",
      markdown: "## C1. Entry Hall {#c1}\n\nThe door grinds open. It is cold.\n",
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ links: [link] })));
    await waitFor(() => expect(save.disabled).toBe(true));
  });

  it("inserts an attachment at the cursor: an image as an image, a PDF as a link", async () => {
    const { handle } = renderEditor();
    const editor = await editorOf();
    act(() => {
      editor.commands.focus("end");
      handle.current!.insertAttachment({ id: "ritualist-token", type: "image/png", sha256: "ab", size: 79, description: "The ritualist", audience: "player" });
    });
    // The toolbar inserts too.
    act(() => {
      editor.commands.focus("end");
    });
    fireEvent.change(screen.getByLabelText("Insert an attachment"), { target: { value: "crypt-plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(puts()).toHaveLength(1));
    expect(JSON.parse(String(puts()[0][1].body)).markdown).toBe(
      "## C1. Entry Hall {#c1}\n\nThe door grinds open.\n\n![The ritualist](asset:ritualist-token)\n\n[The crypt's plan](asset:crypt-plan)\n",
    );
  });

  it("asks before leaving with unsaved changes", async () => {
    const { router } = renderEditor();
    const editor = await editorOf();
    act(() => {
      editor.chain().focus("end").insertContent(" Changed.").run();
    });
    await waitFor(() => expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(false));
    await act(async () => {
      await router.navigate("/elsewhere");
    });
    await screen.findByRole("alertdialog", { name: "This text has unsaved changes. Leave anyway?" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(router.state.location.pathname).toBe(`/modules/${MODULE}`);
  });
});
