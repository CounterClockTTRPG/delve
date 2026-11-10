import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BackedUpInstall, BackupItem } from "../cloud/api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import Restore from "./Restore";

const HERE = "ins_000000000001";
const OLD = "ins_00000000000f";

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;
let installs: BackedUpInstall[];
let items: Record<string, BackupItem[]>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function bodies(method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([p, init]) => p === path && init?.method === method)
    .map(([, init]) => (init.body === undefined ? undefined : JSON.parse(String(init.body))));
}

const item = (overrides: Partial<BackupItem> & Pick<BackupItem, "kind" | "item_id" | "title">): BackupItem => ({
  hash: "h",
  size: 2_400_000,
  backed_up_at: "2026-10-25T04:00:00+00:00",
  on_install: true,
  exists_here: false,
  ...overrides,
});

beforeEach(() => {
  installs = [
    { install_id: OLD, name: "Old laptop", updated_at: "2026-09-01T04:00:00+00:00" },
    { install_id: HERE, name: "Study", updated_at: "2026-10-25T04:00:00+00:00" },
  ];
  items = {
    [HERE]: [
      item({ kind: "module", item_id: "mod_1", title: "The Sunken Crypt" }),
      item({ kind: "setting", item_id: "set_1", title: "Greyhawk", exists_here: true }),
      item({ kind: "campaign", item_id: "cmp_1", title: "Tuesday crypt", module_id: "mod_1", setting_id: "set_1" }),
      item({ kind: "campaign", item_id: "cmp_2", title: "Old table", exists_here: true, module_id: "mod_2", setting_id: null }),
      item({ kind: "module", item_id: "mod_3", title: "Gone module", on_install: false, size: 800 }),
    ],
    [OLD]: [item({ kind: "module", item_id: "mod_9", title: "Laptop module" })],
  };
  routes = {
    "GET /api/storage/backups": () => json(200, installs),
    [`GET /api/storage/backups/${HERE}`]: () => json(200, items[HERE]),
    [`GET /api/storage/backups/${OLD}`]: () => json(200, items[OLD]),
    "POST /api/storage/restore": (init) => {
      const body = JSON.parse(String(init?.body));
      return json(
        200,
        body.items.map((i: { kind: string; item_id: string }) => ({ ...i, ok: true, warnings: [], error: null })),
      );
    },
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderRestore() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <Restore installId={HERE} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const box = (title: string) => screen.getByRole("checkbox", { name: title }) as HTMLInputElement;

describe("Restore", () => {
  it("lists this install first, and each item with what it is and where", async () => {
    renderRestore();
    const picker = (await screen.findByLabelText("Backups of")) as HTMLSelectElement;
    expect([...picker.options].map((o) => o.textContent)).toEqual(["Study (this install)", "Old laptop"]);
    expect(picker.value).toBe(HERE);

    const crypt = (await screen.findByRole("checkbox", { name: "The Sunken Crypt" })).closest("tr")!;
    expect(within(crypt).getByText("Module")).toBeTruthy();
    expect(within(crypt).getByText("2.4 MB")).toBeTruthy();
    expect(within(crypt).getByText("Not on this install")).toBeTruthy();
    expect(within(box("Greyhawk").closest("tr")!).getByText("On this install")).toBeTruthy();
    expect(within(box("Gone module").closest("tr")!).getByText("No longer on this install")).toBeTruthy();
  });

  it("switches to another install's backups", async () => {
    renderRestore();
    fireEvent.change(await screen.findByLabelText("Backups of"), { target: { value: OLD } });
    expect(await screen.findByRole("checkbox", { name: "Laptop module" })).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: "The Sunken Crypt" })).toBeNull();
  });

  it("a campaign's module is ticked with it", async () => {
    renderRestore();
    await screen.findByRole("checkbox", { name: "Tuesday crypt" });
    fireEvent.click(box("Tuesday crypt"));

    // Its module isn't here, so it comes along, ticked and locked; its setting is here, so it stays as it is.
    expect(box("The Sunken Crypt").checked).toBe(true);
    expect(box("The Sunken Crypt").disabled).toBe(true);
    expect(within(box("The Sunken Crypt").closest("tr")!).getByText("Comes with Tuesday crypt")).toBeTruthy();
    expect(box("Greyhawk").checked).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));
    await waitFor(() =>
      expect(bodies("POST", "/api/storage/restore")).toEqual([
        {
          install_id: HERE,
          items: [
            { kind: "module", item_id: "mod_1" },
            { kind: "campaign", item_id: "cmp_1" },
          ],
          replace: false,
        },
      ]),
    );
    expect(await screen.findByText("Tuesday crypt: restored")).toBeTruthy();

    // Unticking the campaign lets its module go.
    fireEvent.click(box("Tuesday crypt"));
    expect(box("The Sunken Crypt").checked).toBe(false);
    expect(box("The Sunken Crypt").disabled).toBe(false);
  });

  it("restore asks before replacing an existing campaign", async () => {
    renderRestore();
    await screen.findByRole("checkbox", { name: "Old table" });
    fireEvent.click(box("Old table"));
    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));

    let dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Replace what is on this install?")).toBeTruthy();
    expect(within(dialog).getByText(/Old table/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(bodies("POST", "/api/storage/restore")).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));
    dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Replace" }));
    await waitFor(() =>
      expect(bodies("POST", "/api/storage/restore")).toEqual([
        { install_id: HERE, items: [{ kind: "campaign", item_id: "cmp_2" }], replace: true },
      ]),
    );
  });

  it("shows what didn't restore, and what came along", async () => {
    routes["POST /api/storage/restore"] = () =>
      json(200, [
        { kind: "module", item_id: "mod_1", ok: true, warnings: [], error: null, added: true },
        { kind: "campaign", item_id: "cmp_1", ok: false, warnings: [], error: "The bundle is from a newer Delve." },
      ]);
    renderRestore();
    await screen.findByRole("checkbox", { name: "Tuesday crypt" });
    fireEvent.click(box("Tuesday crypt"));
    fireEvent.click(screen.getByRole("button", { name: "Restore selected" }));
    expect(await screen.findByText("The Sunken Crypt: restored, brought along")).toBeTruthy();
    expect(screen.getByText("Tuesday crypt: not restored: The bundle is from a newer Delve.")).toBeTruthy();
  });

  it("restores nothing until something is ticked", async () => {
    renderRestore();
    await screen.findByRole("checkbox", { name: "Tuesday crypt" });
    expect((screen.getByRole("button", { name: "Restore selected" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
