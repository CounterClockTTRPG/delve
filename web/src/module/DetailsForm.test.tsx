import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Attachment, ModuleDetail } from "../api";
import { I18nProvider } from "../i18n";
import DetailsForm from "./DetailsForm";

const MODULE = "mod_0123456789ab";
const module: ModuleDetail = {
  id: MODULE,
  title: "The Crypt of Saint Vellis",
  metadata: {
    authors: [{ name: "dungml samples", role: "author" }, "A. Playtester"],
    system: "adnd2e",
    setting: "generic",
    tags: ["dungeon", "undead"],
    content_warnings: ["human remains"],
    party: { notes: "A cleric helps against the risen saint.", size: 4 },
    release: { version: "1.1.0" },
    cover: "asset:ritualist-token",
  },
  maps: [],
  head_revision: 1,
  updated_at: "2026-10-17T10:00:00Z",
  draft: false,
};
const attachments: Attachment[] = [
  { id: "ritualist-token", type: "image/png", sha256: "aa", size: 79, description: "Cult ritualist token", audience: "player" },
  { id: "crypt-plan", type: "application/pdf", sha256: "bb", size: 99, description: "The plan", audience: "gm" },
];

let reply: (body: { title: string; metadata: Record<string, unknown> }) => Response;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  reply = (body) => json(200, { ...module, ...body });
  fetchMock = vi.fn(async (_path: string, init?: RequestInit) => reply(JSON.parse(String(init?.body))));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderForm(onSaved = vi.fn(), shown: ModuleDetail = module) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DetailsForm module={shown} attachments={attachments} onSaved={onSaved} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return onSaved;
}

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

function sent() {
  const patches = fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH");
  expect(patches).toHaveLength(1);
  expect(patches[0][0]).toBe(`/api/modules/${MODULE}`);
  return JSON.parse(String(patches[0][1].body));
}

describe("DetailsForm", () => {
  it("shows the module's metadata", () => {
    renderForm();
    expect((screen.getByLabelText("Module title") as HTMLInputElement).value).toBe("The Crypt of Saint Vellis");
    expect((screen.getByLabelText("Author 1") as HTMLInputElement).value).toBe("dungml samples");
    expect((screen.getByLabelText("Role of author 1") as HTMLSelectElement).value).toBe("author");
    expect((screen.getByLabelText("Author 2") as HTMLInputElement).value).toBe("A. Playtester");
    expect((screen.getByLabelText("Tags") as HTMLInputElement).value).toBe("dungeon, undead");
    expect((screen.getByLabelText("Fewest characters") as HTMLInputElement).value).toBe("4");
    expect((screen.getByLabelText("Party notes") as HTMLTextAreaElement).value).toBe("A cleric helps against the risen saint.");
    // The cover is one of the image attachments.
    const cover = screen.getByLabelText("Cover") as HTMLSelectElement;
    expect(cover.value).toBe("ritualist-token");
    expect([...cover.options].map((o) => o.value)).toEqual(["", "ritualist-token"]);
  });

  it("sends the metadata with the party's levels and size, keeping what it doesn't show", async () => {
    const onSaved = renderForm();
    type("Module title", "The Crypt of Saint Vellis, revised");
    type("Lowest level", "1");
    type("Highest level", "3");
    type("Recommended level", "2");
    type("Fewest characters", "3");
    type("Most characters", "6");
    type("Tags", "dungeon, undead, one-shot, dungeon");
    type("Content warnings", "");
    type("Setting", "Greyhawk");
    fireEvent.click(screen.getByRole("button", { name: "Add an author" }));
    type("Author 3", "Raf");
    type("Role of author 3", "cartographer");
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(sent()).toEqual({
      title: "The Crypt of Saint Vellis, revised",
      metadata: {
        authors: [{ name: "dungml samples", role: "author" }, "A. Playtester", { name: "Raf", role: "cartographer" }],
        system: "adnd2e",
        setting: "Greyhawk",
        tags: ["dungeon", "undead", "one-shot"],
        party: {
          notes: "A cleric helps against the risen saint.",
          levels: { min: 1, max: 3, recommended: 2 },
          size: { min: 3, max: 6 },
        },
        release: { version: "1.1.0" },
        cover: "asset:ritualist-token",
      },
    });
  });

  it("shows, edits and empties the summary and the description (DEL-360)", async () => {
    const onSaved = renderForm(vi.fn(), { ...module, metadata: { ...module.metadata, summary: "A saint rises.", description: "Old." } });
    expect((screen.getByLabelText("Summary") as HTMLInputElement).value).toBe("A saint rises.");
    expect((screen.getByLabelText("Description") as HTMLTextAreaElement).value).toBe("Old.");
    type("Summary", "  The risen saint walks the crypt.  ");
    type("Description", " ");
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(sent().metadata.summary).toBe("The risen saint walks the crypt.");
    expect(sent().metadata).not.toHaveProperty("description");
  });

  it("saves the party's notes, trimmed (DEL-16)", async () => {
    const onSaved = renderForm();
    type("Party notes", "  A cleric is a must.  ");
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(sent().metadata.party).toEqual({ notes: "A cleric is a must.", size: 4 });
  });

  it("takes the party's notes out when they are emptied", async () => {
    const onSaved = renderForm();
    type("Party notes", " ");
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(sent().metadata.party).toEqual({ size: 4 });
  });

  it("adds and takes out the homebrew tag with its box (DEL-226)", async () => {
    const onSaved = renderForm();
    const box = screen.getByRole("checkbox", { name: /Homebrew/ }) as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    expect((screen.getByLabelText("Tags") as HTMLInputElement).value).toMatch(/, homebrew$/);
    type("Tags", "dungeon, Homebrew");
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect((screen.getByLabelText("Tags") as HTMLInputElement).value).toBe("dungeon");
    fireEvent.click(box);
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(sent().metadata.tags).toEqual(["dungeon", "homebrew"]);
  });

  it("shows the server's refusal beside its field", async () => {
    reply = () =>
      json(422, {
        error: "The metadata doesn't fit the module schema.",
        diagnostics: [{ severity: "error", code: "range", message: "min is more than max", path: "party/levels" }],
      });
    renderForm();
    type("Lowest level", "5");
    type("Highest level", "3");
    fireEvent.click(screen.getByRole("button", { name: "Save details" }));
    const message = await screen.findByText("min is more than max");
    expect(within(message.closest("fieldset") as HTMLElement).getByLabelText("Lowest level")).toBeTruthy();
  });
});
