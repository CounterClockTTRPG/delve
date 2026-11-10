import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import TransferTab from "../setting/TransferTab";
import Packs, { RESTART_WAIT_MS } from "./Packs";
import type { PacksView } from "./packs";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function view(over: Partial<PacksView> = {}): PacksView {
  return {
    packs: [
      { id: "adnd2e", kind: "ruleset", title: "AD&D 2nd edition", version: "1.0.0", active: true, campaigns: ["Tuesday"] },
      { id: "greyhawk", kind: "setting", title: "Greyhawk", version: "1.1.0", active: false, campaigns: [] },
    ],
    removed: [],
    can_install: true,
    restart: { possible: true, needed: true, beats: ["Tuesday"], conversion: null },
    ...over,
  };
}

function shown(ui = <Packs />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <MemoryRouter>{ui}</MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

async function confirmDialog(button: string) {
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: button }));
  return dialog;
}

describe("Packs (DEL-366)", () => {
  it("lists the packs with Download, marks one waiting for a restart, and lets an organiser do no more", async () => {
    stubFetch({ "GET /api/packs": () => json(200, view({ can_install: false })) });
    shown();
    const row = await screen.findByTestId("pack-greyhawk");
    expect(row.textContent).toContain("after a restart");
    expect(within(row).getByRole("link", { name: "Download" }).getAttribute("href")).toBe("/api/packs/greyhawk/download");
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.queryByTestId("pack-file")).toBeNull();
    expect(screen.getByTestId("packs-restart").textContent).toContain("Delve uses them once it restarts");
    expect(screen.queryByRole("button", { name: "Restart Delve now" })).toBeNull();
  });

  it("installs a .delvepack after saying it runs code on the server", async () => {
    const fetchMock = stubFetch({
      "GET /api/packs": () => json(200, view()),
      "POST /api/packs": () => json(201, { pack: view().packs[1], restart: view().restart }),
    });
    shown();
    const input = await screen.findByTestId("pack-file");
    const file = new File(["zip"], "greyhawk-1.1.0.delvepack", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [file] } });
    const dialog = await confirmDialog("Install");
    expect(dialog.textContent).toContain("runs on this server");
    await waitFor(() => expect(fetchMock.mock.calls.some(([p, init]) => p === "/api/packs" && init?.method === "POST")).toBe(true));
    const [, init] = fetchMock.mock.calls.find(([p, i]) => p === "/api/packs" && i?.method === "POST")!;
    expect(init?.body).toBe(file);
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/zip");
    expect(await screen.findByText("Installed Greyhawk 1.1.0.")).toBeTruthy();
  });

  it("removes a pack campaigns use only after naming them, then with force", async () => {
    const fetchMock = stubFetch({
      "GET /api/packs": () => json(200, view()),
      "DELETE /api/packs/adnd2e?force=true": () => json(200, { restart: view().restart }),
    });
    shown();
    const row = await screen.findByTestId("pack-adnd2e");
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    const dialog = await confirmDialog("Remove");
    expect(dialog.textContent).toContain("Tuesday");
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === "/api/packs/adnd2e?force=true" && init?.method === "DELETE")).toBe(true),
    );
  });

  it("restarts Delve after saying what it breaks off, then reads the packs again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let state = view();
    const fetchMock = stubFetch({
      "GET /api/packs": () => json(200, state),
      "POST /api/restart": () => json(202, { restarting: true, beats: ["Tuesday"], conversion: null }),
    });
    shown();
    fireEvent.click(await screen.findByRole("button", { name: "Restart Delve now" }));
    const dialog = await confirmDialog("Restart Delve now");
    expect(dialog.textContent).toContain("The DM is answering at Tuesday");
    await waitFor(() => expect(screen.getByTestId("packs-restart").textContent).toContain("Delve is restarting"));
    state = view({ restart: { possible: true, needed: false, beats: [], conversion: null } });
    await act(async () => {
      vi.advanceTimersByTime(RESTART_WAIT_MS);
    });
    expect(await screen.findByTestId("packs-restarted")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([p]) => p === "/api/packs").length).toBeGreaterThan(1);
  });
});

describe("a setting's Export and import (DEL-366)", () => {
  it("links the export, and imports a file keeping or replacing what is here", async () => {
    const fetchMock = stubFetch({
      "POST /api/settings/greyhawk/additions?keep=false": () =>
        json(200, {
          imported: { pages_added: 2, pages_replaced: 1, pages_kept: 0, facts_added: 4, facts_kept: 1, maps_added: 1, maps_replaced: 0, maps_kept: 0 },
        }),
    });
    shown(<TransferTab settingId="greyhawk" />);
    expect(screen.getByTestId("transfer-export-link").getAttribute("href")).toBe("/api/settings/greyhawk/additions/export");
    fireEvent.click(screen.getByLabelText("Take the file's"));
    fireEvent.change(screen.getByTestId("transfer-file"), { target: { files: [new File(["zip"], "a.zip")] } });
    expect((await screen.findByTestId("transfer-done")).textContent).toBe(
      "Imported 3 page(s), 4 fact(s) and 1 map(s); 1 kept as they were.",
    );
    expect(fetchMock).toHaveBeenCalled();
  });
});
