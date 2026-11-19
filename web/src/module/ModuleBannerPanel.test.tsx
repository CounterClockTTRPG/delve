import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Attachment, ModuleDetail } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import ModuleBannerPanel from "./ModuleBannerPanel";

const module = { id: "mod_crypt", title: "The Crypt", maps: [], head_revision: null, updated_at: "", draft: false, metadata: {}, banner: null } as unknown as ModuleDetail;
const cover: Attachment = { id: "page-1", type: "image/png", sha256: "s", size: 1, description: "The cover", audience: "gm" };
const handout: Attachment = { id: "notes", type: "application/pdf", sha256: "p", size: 1, description: "", audience: "gm" };

let calls: { method: string; path: string; body: unknown }[];
function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
    calls.push({ method: init?.method ?? "GET", path, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path.endsWith("/banner/paint") && (init?.method ?? "GET") === "GET") return json(200, { paid: true, allowed: true });
    return json(200, { ...module, banner: { version: "v1", source: "picture:page-1", status: null, error: null } });
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderPanel(attachments: Attachment[] = [cover, handout]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <ModuleBannerPanel module={module} attachments={attachments} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("ModuleBannerPanel", () => {
  it("says a paid model costs money, and offers only the module's pictures", async () => {
    renderPanel();
    expect(await screen.findByText("Painting costs money with the image model chosen in Preferences.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Use one of the module's pictures" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("The cover")).toBeTruthy();
  });

  it("cuts a picked picture where the sliders say, as the preview shows it", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Use one of the module's pictures" }));
    fireEvent.click(screen.getByText("The cover"));
    const preview = screen.getByRole("img", { name: "The banner as it will be cut" }) as HTMLImageElement;
    fireEvent.change(screen.getByRole("slider", { name: "Down" }), { target: { value: "20" } });
    expect(preview.style.objectPosition).toBe("50% 20%");
    // A 2100 × 1800 cover: the widest band is 2100 × 900; half of it, 1050 × 450, at the right and 20% down.
    Object.defineProperty(preview, "naturalWidth", { value: 2100 });
    Object.defineProperty(preview, "naturalHeight", { value: 1800 });
    fireEvent.load(preview);
    fireEvent.change(screen.getByRole("slider", { name: "Width" }), { target: { value: "50" } });
    fireEvent.change(screen.getByRole("slider", { name: "Across" }), { target: { value: "100" } });
    expect([preview.style.width, preview.style.height, preview.style.left, preview.style.top]).toEqual(["200%", "400%", "-100%", "-60%"]);
    fireEvent.click(screen.getByRole("button", { name: "Use as banner" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")).toEqual({
      method: "PUT",
      path: "/api/modules/mod_crypt/banner",
      body: { picture: "page-1", x: 1, y: 0.2, width: 0.5 },
    });
  });

  it("can't move the whole band across a tall picture, only down", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Use one of the module's pictures" }));
    fireEvent.click(screen.getByText("The cover"));
    const preview = screen.getByRole("img", { name: "The banner as it will be cut" });
    Object.defineProperty(preview, "naturalWidth", { value: 2100 });
    Object.defineProperty(preview, "naturalHeight", { value: 1800 });
    fireEvent.load(preview);
    expect((screen.getByRole("slider", { name: "Across" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("slider", { name: "Down" }) as HTMLInputElement).disabled).toBe(false);
  });

  it("offers no picking when the module has no picture", async () => {
    renderPanel([handout]);
    await screen.findByRole("button", { name: "Paint a banner" });
    expect(screen.queryByRole("button", { name: "Use one of the module's pictures" })).toBeNull();
  });
});
