import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BackupRun, StorageState, StoreView } from "../cloud/api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import Storage from "./Storage";

const SAS = "sv=2024-05-04&sp=racwdl&sig=SECRET-XYZZY";
const SECRET_KEY = "s3-SECRET-XYZZY";

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;
let state: StorageState;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function bodies(method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([p, init]) => p === path && init?.method === method)
    .map(([, init]) => (init.body === undefined ? undefined : JSON.parse(String(init.body))));
}

const azure = (overrides: Partial<StoreView> = {}): StoreView => ({
  provider: "azure",
  label: "https://delvebackups.blob.core.windows.net/delve",
  secret: "set",
  right: "manage",
  expires: null,
  choice: null,
  ...overrides,
});

const r2 = (overrides: Partial<StoreView> = {}): StoreView => ({
  provider: "s3",
  label: "https://0123abcd.r2.cloudflarestorage.com/library",
  secret: "set",
  right: "publish",
  expires: null,
  choice: "publish",
  ...overrides,
});

beforeEach(() => {
  state = { backup: null, library: null, schedule: { time: "04:00", last_run: null }, install_id: "ins_000000000001" };
  routes = {
    "GET /api/storage": () => json(200, state),
    "GET /api/storage/backups": () => json(200, []),
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function renderStorage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <Storage />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const backupCard = () => screen.getByRole("group", { name: "Backup store" });
const libraryCard = () => screen.getByRole("group", { name: "Library store" });

describe("Storage", () => {
  it("shows the owner the two stores", async () => {
    renderStorage();
    expect(await screen.findByRole("heading", { level: 2, name: "Storage" })).toBeTruthy();
    expect(backupCard()).toBeTruthy();
    expect(libraryCard()).toBeTruthy();
    // No backup store: nothing to back up to, and nothing to restore from.
    expect(screen.queryByRole("button", { name: "Back up now" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Restore" })).toBeNull();
  });

  it("the section is hidden from an organiser", async () => {
    routes["GET /api/storage"] = () => json(403, { error: "Only the install's owner can do this." });
    const { container } = renderStorage();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/storage", expect.anything()));
    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(screen.queryByText("Only the install's owner can do this.")).toBeNull();
  });

  it("offers each provider's fields", async () => {
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    const card = libraryCard();
    const provider = within(card).getByLabelText("Provider") as HTMLSelectElement;
    expect([...provider.options].map((o) => o.textContent)).toEqual(["Azure Blob Storage", "Cloudflare R2", "S3-compatible"]);

    expect((within(card).getByLabelText("SAS URL") as HTMLInputElement).type).toBe("password");

    fireEvent.change(provider, { target: { value: "r2" } });
    for (const label of ["Account id", "Bucket", "Access key id", "Secret access key"]) expect(within(card).getByLabelText(label)).toBeTruthy();
    expect(within(card).getByLabelText("Write key gives")).toBeTruthy();
    expect(within(card).getByText(/On R2 the storage can't tell publish from manage/)).toBeTruthy();

    fireEvent.change(provider, { target: { value: "s3" } });
    for (const label of ["Endpoint", "Bucket", "Access key id", "Secret access key"]) expect(within(card).getByLabelText(label)).toBeTruthy();

    // The backup store needs manage anyway: no choice there.
    fireEvent.change(within(backupCard()).getByLabelText("Provider"), { target: { value: "r2" } });
    expect(within(backupCard()).queryByLabelText("Write key gives")).toBeNull();
  });

  it("sends R2's endpoint from its account id", async () => {
    routes["PUT /api/storage/library"] = () => json(200, r2());
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    const card = libraryCard();
    fireEvent.change(within(card).getByLabelText("Provider"), { target: { value: "r2" } });
    fireEvent.change(within(card).getByLabelText("Account id"), { target: { value: "0123abcd" } });
    fireEvent.change(within(card).getByLabelText("Bucket"), { target: { value: "library" } });
    fireEvent.change(within(card).getByLabelText("Access key id"), { target: { value: "AKID" } });
    fireEvent.change(within(card).getByLabelText("Secret access key"), { target: { value: SECRET_KEY } });
    fireEvent.change(within(card).getByLabelText("Write key gives"), { target: { value: "manage" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(bodies("PUT", "/api/storage/library")).toEqual([
        {
          provider: "s3",
          endpoint: "https://0123abcd.r2.cloudflarestorage.com",
          bucket: "library",
          access_key_id: "AKID",
          secret_access_key: SECRET_KEY,
          right: "manage",
        },
      ]),
    );
    await waitFor(() => expect((within(card).getByLabelText("Secret access key") as HTMLInputElement).value).toBe(""));
    expect(document.body.innerHTML).not.toContain(SECRET_KEY);
  });

  it("never shows a stored secret", async () => {
    state.backup = azure();
    state.library = r2();
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });

    const sas = within(backupCard()).getByLabelText("SAS URL") as HTMLInputElement;
    expect(sas.type).toBe("password");
    expect(sas.value).toBe("");
    expect(sas.placeholder).toBe("Set: leave empty to keep it");
    expect(within(backupCard()).getByText("https://delvebackups.blob.core.windows.net/delve")).toBeTruthy();

    // A stored R2 store comes back as R2, its account and bucket shown, its secret not.
    expect((within(libraryCard()).getByLabelText("Provider") as HTMLSelectElement).value).toBe("r2");
    expect((within(libraryCard()).getByLabelText("Account id") as HTMLInputElement).value).toBe("0123abcd");
    expect((within(libraryCard()).getByLabelText("Bucket") as HTMLInputElement).value).toBe("library");
    const secret = within(libraryCard()).getByLabelText("Secret access key") as HTMLInputElement;
    expect(secret.type).toBe("password");
    expect(secret.value).toBe("");
    expect(document.body.innerHTML).not.toContain("sig=");
  });

  it("a blank secret keeps the stored one", async () => {
    state.backup = azure();
    state.library = r2();
    routes["PUT /api/storage/backup"] = () => json(200, azure());
    routes["PUT /api/storage/library"] = () => json(200, r2());
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });

    fireEvent.click(within(backupCard()).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies("PUT", "/api/storage/backup")).toEqual([{ provider: "azure" }]));

    const card = libraryCard();
    fireEvent.change(within(card).getByLabelText("Access key id"), { target: { value: "AKID" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(bodies("PUT", "/api/storage/library")).toEqual([
        { provider: "s3", endpoint: "https://0123abcd.r2.cloudflarestorage.com", bucket: "library", access_key_id: "AKID", right: "publish" },
      ]),
    );
  });

  it("a new store needs its secret", async () => {
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    expect((within(backupCard()).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(backupCard()).getByLabelText("SAS URL"), {
      target: { value: `https://delvebackups.blob.core.windows.net/delve?${SAS}` },
    });
    expect((within(backupCard()).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("shows why a store was refused", async () => {
    routes["PUT /api/storage/backup"] = () => json(422, { error: "This credential can't write and delete, so backups can't use it." });
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    fireEvent.change(within(backupCard()).getByLabelText("SAS URL"), {
      target: { value: `https://delvebackups.blob.core.windows.net/delve?${SAS}` },
    });
    fireEvent.click(within(backupCard()).getByRole("button", { name: "Save" }));
    expect(await within(backupCard()).findByText("Not saved: This credential can't write and delete, so backups can't use it.")).toBeTruthy();
    expect(document.body.innerHTML).not.toContain("SECRET-XYZZY");
  });

  it("shows the right after a test", async () => {
    state.library = azure({ label: "https://friends.blob.core.windows.net/library", right: null });
    routes["POST /api/storage/library/test"] = () => {
      state.library = { ...state.library!, right: "read" };
      return json(200, { ok: true, right: "read", message: "Delve can read the library." });
    };
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    const card = libraryCard();
    expect(within(card).getByText("Right: Not known yet")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Test" }));
    expect(await within(card).findByText("Delve can read the library.")).toBeTruthy();
    expect(within(card).getByText("Right: Read")).toBeTruthy();
  });

  it("asks before removing a store", async () => {
    state.library = r2();
    routes["DELETE /api/storage/library"] = () => {
      state.library = null;
      return json(200, null);
    };
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    fireEvent.click(within(libraryCard()).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Remove the library store?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(bodies("DELETE", "/api/storage/library")).toHaveLength(1));
    await waitFor(() => expect(within(libraryCard()).queryByRole("button", { name: "Remove" })).toBeNull());
  });

  it.each([
    [40, "ok", /^SAS expires on /],
    [5, "soon", /^SAS expires in 5 days, on /],
    [-2, "past", /^SAS expired on .*: Delve can't reach this store until you save a new one\.$/],
  ] as const)("an Azure SAS %i days from expiry is %s", async (days, tone, words) => {
    state.backup = azure({ expires: new Date(Date.now() + days * 24 * 60 * 60 * 1000 + 60_000).toISOString() });
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    const expiry = within(backupCard()).getByText(words);
    expect(expiry.closest(".store-expiry")!.className).toContain(`expiry-${tone}`);
  });

  it("saves the backup time", async () => {
    state.backup = azure();
    routes["PUT /api/storage/schedule"] = () => json(200, { time: "02:30", last_run: null });
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    const time = screen.getByLabelText("Back up daily at") as HTMLInputElement;
    expect(time.value).toBe("04:00");
    fireEvent.change(time, { target: { value: "02:30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save time" }));
    await waitFor(() => expect(bodies("PUT", "/api/storage/schedule")).toEqual([{ time: "02:30" }]));
  });

  it("back up now shows a partial run's failures", async () => {
    state.backup = azure();
    const partial: BackupRun = {
      started_at: "2026-10-26T09:00:00+00:00",
      finished_at: "2026-10-26T09:01:00+00:00",
      uploaded: ["module/mod_1", "campaign/cmp_1"],
      unchanged: 3,
      failed: [{ kind: "setting", item_id: "set_1", title: "Greyhawk", error: "Azure answered 413." }],
      status: "partial",
    };
    routes["POST /api/storage/backup"] = () => {
      state.schedule = { ...state.schedule, last_run: partial };
      return json(202, {});
    };
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    expect(screen.getByText("No backup has run yet.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Back up now" }));

    const run = await screen.findByRole("region", { name: "Last backup" }, { timeout: 4000 });
    await waitFor(() => expect(within(run).getByText(/Partly backed up/)).toBeTruthy(), { timeout: 4000 });
    expect(within(run).queryByText(/^Backed up/)).toBeNull();
    expect(within(run).getByText("2 uploaded, 3 unchanged, 1 failed")).toBeTruthy();
    expect(within(run).getByText("Greyhawk (Setting): Azure answered 413.")).toBeTruthy();
  });

  it("reads the Restore list again when a run ends", async () => {
    state.backup = azure();
    const done: BackupRun = {
      started_at: "2026-10-26T09:00:00+00:00",
      finished_at: "2026-10-26T09:01:00+00:00",
      uploaded: ["The Crypt"],
      unchanged: 0,
      failed: [],
      status: "ok",
    };
    let backedUp = false;
    routes["POST /api/storage/backup"] = () => {
      state.schedule = { ...state.schedule, running: true };
      return json(202, {});
    };
    let fetches = 0;
    routes["GET /api/storage"] = () => {
      // The run ends after the first look, later than Back up now's answer.
      if (state.schedule.running && ++fetches > 1) {
        state.schedule = { ...state.schedule, running: false, last_run: done };
        backedUp = true;
      }
      return json(200, state);
    };
    routes["GET /api/storage/backups"] = () =>
      json(200, backedUp ? [{ install_id: state.install_id, name: "tower", updated_at: done.finished_at }] : []);
    routes[`GET /api/storage/backups/${state.install_id}`] = () => json(200, []);
    renderStorage();
    expect(await screen.findByText("Nothing is backed up yet.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Back up now" }));

    expect(await screen.findByRole("option", { name: "tower (this install)" }, { timeout: 4000 })).toBeTruthy();
  });

  it("stops waiting when a run ends without a result", async () => {
    state.backup = azure();
    routes["POST /api/storage/backup"] = () => {
      state.schedule = { ...state.schedule, running: true };
      return json(202, {});
    };
    let fetches = 0;
    routes["GET /api/storage"] = () => {
      // The run dies after the first look: no last_run is written, and the server says nothing runs.
      if (state.schedule.running && ++fetches > 1) state.schedule = { ...state.schedule, running: false };
      return json(200, state);
    };
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });

    fireEvent.click(screen.getByRole("button", { name: "Back up now" }));

    expect(await screen.findByRole("button", { name: "Backing up…" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Back up now" }, { timeout: 4000 })).toBeTruthy();
    expect(screen.getByText("No backup has run yet.")).toBeTruthy();
  });

  it.each([["The backup's list"], [""]])("names a failure of the backup's list (title %j)", async (title) => {
    state.backup = azure();
    state.schedule.last_run = {
      started_at: "2026-10-26T09:00:00+00:00",
      finished_at: "2026-10-26T09:01:00+00:00",
      uploaded: [],
      unchanged: 0,
      failed: [{ kind: "index", item_id: "index.json", title, error: "Azure answered 403." }],
      status: "failed",
    };
    renderStorage();
    const run = await screen.findByRole("region", { name: "Last backup" });
    expect(within(run).getByRole("listitem").textContent).toBe("The backup's list: Azure answered 403.");
  });

  it("says a backup is already running", async () => {
    state.backup = azure();
    routes["POST /api/storage/backup"] = () => json(409, { error: "A backup is running." });
    renderStorage();
    await screen.findByRole("heading", { name: "Storage" });
    fireEvent.click(screen.getByRole("button", { name: "Back up now" }));
    expect(await screen.findByText("A backup is already running.")).toBeTruthy();
  });
});

describe("Files nothing uses (DEL-36)", () => {
  const found = {
    count: 212,
    size: 547_853_013,
    kept: 4,
    kinds: [
      { mime: "image/png", count: 210, size: 400_000_000 },
      { mime: null, count: 2, size: 147_853_013 },
    ],
  };

  it("looks, lists what would go, and deletes it once confirmed", async () => {
    routes["GET /api/storage/unused"] = () => json(200, found);
    routes["POST /api/storage/unused/delete"] = () => json(200, found);
    renderStorage();
    const section = await screen.findByRole("region", { name: "Files nothing uses" });
    expect(within(section).queryByRole("button", { name: "Delete them" })).toBeNull();

    fireEvent.click(within(section).getByRole("button", { name: "Look for them" }));
    expect(await within(section).findByText("Files nothing uses: 212, 547.9 MB in all.")).toBeTruthy();
    expect(within(section).getByText("image/png: 210, 400 MB")).toBeTruthy();
    expect(within(section).getByText("files without their record: 2, 147.9 MB")).toBeTruthy();
    expect(within(section).getByText("Newer files nothing uses yet, which stay: 4.")).toBeTruthy();
    expect(bodies("POST", "/api/storage/unused/delete")).toEqual([]);

    fireEvent.click(within(section).getByRole("button", { name: "Delete them" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Delete the files nothing uses (547.9 MB)?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete them" }));
    expect(await within(section).findByText("Deleted files: 212, 547.9 MB.")).toBeTruthy();
    expect(bodies("POST", "/api/storage/unused/delete")).toHaveLength(1);
    expect(within(section).queryByRole("button", { name: "Delete them" })).toBeNull();
  });

  it("says when every file is in use, and offers nothing to delete", async () => {
    routes["GET /api/storage/unused"] = () => json(200, { count: 0, size: 0, kept: 0, kinds: [] });
    renderStorage();
    const section = await screen.findByRole("region", { name: "Files nothing uses" });
    fireEvent.click(within(section).getByRole("button", { name: "Look for them" }));
    expect(await within(section).findByText("Every stored file is in use.")).toBeTruthy();
    expect(within(section).queryByRole("button", { name: "Delete them" })).toBeNull();
    await waitFor(() => expect(within(section).queryByText(/which stay/)).toBeNull());
  });
});
