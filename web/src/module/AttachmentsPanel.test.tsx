import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Attachment, ModuleTextDoc } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import AttachmentsPanel from "./AttachmentsPanel";

const MODULE = "mod_0123456789ab";
const token: Attachment = {
  id: "ritualist-token",
  type: "image/png",
  sha256: "78b9",
  size: 79,
  description: "Cult ritualist token",
  audience: "player",
};
const page35: Attachment = {
  id: "page-35",
  type: "image/png",
  sha256: "35",
  size: 9,
  description: "Page 35: a map or full-page picture",
  audience: "gm",
};
const crop: Attachment = { ...page35, id: "page-12", description: "Page 12, near “1. Kitchen”" };
const texts: ModuleTextDoc[] = [
  { id: "intro", title: "Introduction", audience: "gm", map: null, markdown: "# Introduction\n\nThe town.\n" },
  { id: "the-haunted-house", title: "The Haunted House", audience: "gm", map: null, markdown: "# The Haunted House\n\n## 1. Kitchen\n\nCold.\n" },
  { id: "the-sea-ghost", title: "The Sea Ghost", audience: "gm", map: "ship", markdown: "# The Sea Ghost\n\n## 1. Main Deck\n\nWet.\n" },
];
const plan: Attachment = { id: "crypt-plan", type: "application/pdf", sha256: "aa", size: 2048, description: "", audience: "gm" };

type Handler = (path: string, init: RequestInit | undefined) => Response;
let handler: Handler;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  handler = (path, init) => {
    if (init?.method === "POST") {
      const name = new URL(path, "http://x").searchParams.get("name")!;
      const type = new Headers(init.headers).get("Content-Type")!;
      return json(201, { id: name.replace(/\.\w+$/, ""), type, sha256: "ff", size: 3, description: "", audience: "gm" });
    }
    if (init?.method === "PATCH") return json(200, { ...token, ...JSON.parse(String(init.body)) });
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    return json(404, { error: "not found" });
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => handler(path, init));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPanel(onInsert = vi.fn(), start: Attachment[] = [token, plan]) {
  function Holder() {
    const [attachments, setAttachments] = useState(start);
    return (
      <AttachmentsPanel moduleId={MODULE} attachments={attachments} texts={texts} onChange={setAttachments} onInsert={onInsert} canInsert />
    );
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <Holder />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return onInsert;
}

function calls(method: string) {
  return fetchMock.mock.calls.filter(([, init]) => init?.method === method);
}

describe("AttachmentsPanel", () => {
  it("shows each attachment: an image as a thumbnail, a PDF by its name", () => {
    renderPanel();
    const image = screen.getByRole("img", { name: "Cult ritualist token" }) as HTMLImageElement;
    expect(image.getAttribute("src")).toBe(`/api/modules/${MODULE}/assets/ritualist-token?v=78b9`);
    expect(screen.getByText("crypt-plan.pdf")).toBeTruthy();
    expect((screen.getByLabelText("Who sees ritualist-token") as HTMLSelectElement).value).toBe("player");
    expect((screen.getByLabelText("Who sees crypt-plan") as HTMLSelectElement).value).toBe("gm");
  });

  it("opens a picture enlarged on a click, and a click closes it (DEL-295)", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: "Enlarge: crypt-plan" })).toBeNull(); // a PDF has no picture
    fireEvent.click(screen.getByRole("button", { name: "Enlarge: ritualist-token" }));
    const dialog = screen.getByRole("dialog", { name: "ritualist-token" });
    expect(within(dialog).getByRole("img").getAttribute("src")).toBe(`/api/modules/${MODULE}/assets/ritualist-token?v=78b9`);
    fireEvent.click(dialog);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("uploads several files, each as its bytes with its type, and lists them", async () => {
    renderPanel();
    const a = new File([new Uint8Array([0x89, 0x50, 0x4e])], "Courtyard.png", { type: "image/png" });
    const b = new File([new Uint8Array([0x25, 0x50, 0x44])], "riddle.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Upload attachments"), { target: { files: [a, b] } });

    expect(await screen.findByLabelText("Description of Courtyard")).toBeTruthy();
    expect(await screen.findByLabelText("Description of riddle")).toBeTruthy();
    const posts = calls("POST");
    expect(posts.map(([path]) => path)).toEqual([
      `/api/modules/${MODULE}/assets?name=Courtyard.png`,
      `/api/modules/${MODULE}/assets?name=riddle.pdf`,
    ]);
    expect(posts.map(([, init]) => new Headers(init.headers).get("Content-Type"))).toEqual(["image/png", "application/pdf"]);
    expect(posts[0][1].body).toBe(a);
  });

  it("says why an upload was refused", async () => {
    handler = () => json(415, { error: "attachments are PNG, JPEG, WebP, GIF, SVG or PDF" });
    renderPanel();
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Upload attachments"), { target: { files: [file] } });
    expect(await screen.findByText("notes.txt: this kind of file can't be attached.")).toBeTruthy();
  });

  it("saves a description and an audience", async () => {
    renderPanel();
    const description = screen.getByLabelText("Description of ritualist-token");
    fireEvent.change(description, { target: { value: "The ritualist's token. Show it when they first see him." } });
    fireEvent.blur(description);
    await waitFor(() => expect(calls("PATCH")).toHaveLength(1));
    expect(calls("PATCH")[0][0]).toBe(`/api/modules/${MODULE}/assets/ritualist-token`);
    expect(JSON.parse(String(calls("PATCH")[0][1].body))).toEqual({
      description: "The ritualist's token. Show it when they first see him.",
    });

    fireEvent.change(screen.getByLabelText("Who sees ritualist-token"), { target: { value: "gm" } });
    await waitFor(() => expect(calls("PATCH")).toHaveLength(2));
    expect(JSON.parse(String(calls("PATCH")[1][1].body))).toEqual({ audience: "gm" });
  });

  it("deletes an attachment after asking", async () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Delete crypt-plan" }));
    await screen.findByRole("alertdialog", { name: /^Delete the attachment crypt-plan\?/ });
    expect(calls("DELETE")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls("DELETE")).toHaveLength(1));
    expect(calls("DELETE")[0][0]).toBe(`/api/modules/${MODULE}/assets/crypt-plan`);
    await waitFor(() => expect(screen.queryByLabelText("Description of crypt-plan")).toBeNull());
  });

  it("Insert in text calls the editor with the attachment", () => {
    const onInsert = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Insert ritualist-token in text" }));
    expect(onInsert).toHaveBeenCalledWith(token);
  });

  it("draws a map from a page of the book for the part chosen", async () => {
    handler = (_path, init) =>
      init?.method === "POST" ? json(202, { id: "cnv_1", kind: "book-map", status: "running" }) : json(404, { error: "not found" });
    renderPanel(vi.fn(), [token, page35, crop, plan]);

    expect(screen.getAllByRole("button", { name: "Draw a map from this page" })).toHaveLength(1);
    const part = screen.getByLabelText("Part") as HTMLSelectElement;
    expect([...part.options].map((o) => o.value)).toEqual(["the-haunted-house", "the-sea-ghost"]);
    fireEvent.change(part, { target: { value: "the-sea-ghost" } });
    fireEvent.click(screen.getByRole("button", { name: "Draw a map from this page" }));

    await waitFor(() => expect(calls("POST")).toHaveLength(1));
    expect(calls("POST")[0][0]).toBe(`/api/modules/${MODULE}/map-drafts/from-book`);
    expect(JSON.parse(String(calls("POST")[0][1].body))).toEqual({ map: null, page: "page-35", part: "the-sea-ghost" });
    expect(await screen.findByText("Drawing the draft…")).toBeTruthy();
  });
});
