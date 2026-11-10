import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Attachment, AttachmentCut } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import AttachmentsPanel from "./AttachmentsPanel";

const MODULE = "mod_0123456789ab";
const ASSETS = `/api/modules/${MODULE}/assets`;
const cabins: Attachment = {
  id: "cabins",
  type: "image/png",
  sha256: "0123456789abcdef",
  size: 900,
  description: "Two cabins",
  audience: "player",
  cut: null,
};
const halfCut: AttachmentCut = {
  original: "0123456789abcdef",
  original_type: "image/png",
  original_size: 900,
  rotate: 0,
  box: [0, 0, 0.5, 1],
  proposed: false,
};

let fetchMock: ReturnType<typeof vi.fn>;
let posted: unknown[];

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  posted = [];
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (init?.method === "POST" && path === `${ASSETS}/cabins/cut`) {
      posted.push(body);
      const pieces = body.pieces.map((piece: { box: number[] | null; description?: string }, n: number) => ({
        ...cabins,
        id: n === 0 ? "cabins" : `cabins-${n + 1}`,
        sha256: `cut${n}aaaaaaaaaaaa`,
        description: piece.description ?? cabins.description,
        cut: { ...halfCut, rotate: body.rotate, box: piece.box },
      }));
      return json(200, { attachments: pieces });
    }
    if (init?.method === "DELETE" && path === `${ASSETS}/cabins/cut`) return json(200, { ...cabins, cut: null });
    if (init?.method === "PATCH") return json(200, { ...cabins, cut: { ...halfCut, proposed: !body.reviewed } });
    return json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function renderPanel(start: Attachment[]) {
  function Holder() {
    const [attachments, setAttachments] = useState(start);
    return <AttachmentsPanel moduleId={MODULE} attachments={attachments} onChange={setAttachments} onInsert={vi.fn()} canInsert />;
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
}

const card = (id: string) => screen.getByRole("img", { name: new RegExp(id === "cabins" ? "^Two cabins$" : id) });

describe("CropDialog", () => {
  it("opens on the original", () => {
    renderPanel([cabins]);
    fireEvent.click(screen.getByRole("button", { name: "Crop cabins" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("img").getAttribute("src")).toBe(`${ASSETS}/cabins?original=true`);
  });

  it("saves a turn, and the card shows the new picture", async () => {
    renderPanel([cabins]);
    expect(card("cabins").getAttribute("src")).toBe(`${ASSETS}/cabins?v=0123456789ab`);
    fireEvent.click(screen.getByRole("button", { name: "Crop cabins" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn right" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posted).toEqual([{ rotate: 90, pieces: [{ box: null }] }]);
    expect(card("cabins").getAttribute("src")).toBe(`${ASSETS}/cabins?v=cut0aaaaaaaa`);
  });

  it("splits into pieces from the current cut", async () => {
    renderPanel([{ ...cabins, cut: halfCut }]);
    fireEvent.click(screen.getByRole("button", { name: "Crop cabins" }));
    fireEvent.click(screen.getByRole("button", { name: "Add piece" }));
    fireEvent.change(screen.getByLabelText("Description of piece 2"), { target: { value: "Cabin B" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posted).toEqual([
      { rotate: 0, pieces: [{ box: [0, 0, 0.5, 1] }, { box: null, description: "Cabin B", audience: "player" }] },
    ]);
    expect(screen.getByLabelText("Description of cabins-2")).toHaveProperty("value", "Cabin B");
  });

  it("turning keeps a box on the same part of the picture", async () => {
    renderPanel([{ ...cabins, cut: halfCut }]);
    fireEvent.click(screen.getByRole("button", { name: "Crop cabins" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn right" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ rotate: 90, pieces: [{ box: [0, 0, 1, 0.5] }] });
  });

  it("a click on the picture keeps the box it had, and a drag draws a new one", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(DOMRect.fromRect({ x: 0, y: 0, width: 200, height: 100 }));
    renderPanel([{ ...cabins, cut: halfCut }]);
    fireEvent.click(screen.getByRole("button", { name: "Crop cabins" }));
    const stage = screen.getByTestId("crop-stage");
    fireEvent.pointerDown(stage, { clientX: 100, clientY: 0, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: 200, clientY: 50, pointerId: 1 });
    fireEvent.pointerUp(stage, { clientX: 200, clientY: 50, pointerId: 1 });
    // A slip of a pixel or two outside the box: not "the whole picture".
    fireEvent.pointerDown(stage, { clientX: 20, clientY: 80, pointerId: 1 });
    fireEvent.pointerMove(stage, { clientX: 21, clientY: 80, pointerId: 1 });
    fireEvent.pointerUp(stage, { clientX: 21, clientY: 80, pointerId: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0]).toEqual({ rotate: 0, pieces: [{ box: [0.5, 0, 0.5, 0.5] }] });
  });

  it("resets a cut", async () => {
    renderPanel([{ ...cabins, cut: halfCut }]);
    fireEvent.click(screen.getByRole("button", { name: "Reset the crop of cabins" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(`${ASSETS}/cabins/cut`, expect.objectContaining({ method: "DELETE" })),
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: "Reset the crop of cabins" })).toBeNull());
  });

  it("marks a proposed crop until it looks right", async () => {
    renderPanel([{ ...cabins, cut: { ...halfCut, proposed: true } }]);
    expect(screen.getByText("Proposed crop")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "The crop of cabins looks right" }));
    await waitFor(() => expect(screen.queryByText("Proposed crop")).toBeNull());
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(patch![1].body))).toEqual({ reviewed: true });
  });

  it("offers no crop for a PDF or an SVG", () => {
    renderPanel([
      { ...cabins, id: "rules", type: "application/pdf" },
      { ...cabins, id: "plan", type: "image/svg+xml" },
    ]);
    expect(screen.queryByRole("button", { name: /^Crop / })).toBeNull();
  });
});
