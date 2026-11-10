import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import { DialogsProvider } from "../components/dialogs";
import Players from "./Players";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ana = {
  id: "acc_00000000000a",
  username: "ana",
  display_name: "Ana",
  organiser: false,
  owner: false,
  disabled: false,
  has_password: true,
  has_email: false,
  created_at: "2026-10-24T10:00:00Z",
  tables: 2,
  pending: false,
  request_note: "",
};
const bo = { ...ana, id: "acc_00000000000b", username: "bo", display_name: "Bo", organiser: true, tables: 0 };
const link = { url: "http://192.168.1.20:7810/account/link/tok-new", expires_at: "2026-10-25T10:00:00Z" };

const ownerMe = { principal: { id: "owner", roles: ["organiser"] }, account: null, seat: null, keepable_seat: null };
const organiserMe = {
  principal: { id: `account:${bo.id}`, roles: ["organiser"] },
  account: { id: bo.id, username: "bo", display_name: "Bo", language: "en", organiser: true, owner: false },
  seat: null,
  keepable_seat: null,
};

function renderPlayers() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter>
          <DialogsProvider>
            <Players />
          </DialogsProvider>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("Players", () => {
  it("marks the accounts that have a confirmed email address, never showing it (DEL-314)", async () => {
    stubFetch({
      "GET /api/me": () => json(200, organiserMe),
      "GET /api/accounts": () => json(200, [{ ...ana, has_email: true }, bo]),
    });
    renderPlayers();
    expect((await screen.findByTestId(`players-row-${ana.id}`)).textContent).toContain("Has an email address");
    expect(screen.getByTestId(`players-row-${bo.id}`).textContent).not.toContain("Has an email address");
  });

  it("adds a player and shows the link", async () => {
    let accounts = [ana, bo];
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const fetchMock = stubFetch({
      "GET /api/me": () => json(200, ownerMe),
      "GET /api/accounts": () => json(200, accounts),
      "POST /api/accounts": () => {
        const cy = { ...ana, id: "acc_00000000000c", username: "cy", display_name: "Cy", has_password: false, tables: 0 };
        accounts = [...accounts, cy];
        return json(201, { account: cy, link });
      },
    });
    renderPlayers();
    expect(await screen.findByRole("heading", { level: 1, name: "Players" })).toBeTruthy();
    const row = await screen.findByTestId(`players-row-${ana.id}`);
    expect(row.textContent).toContain("ana");
    expect(row.textContent).toContain("Ana");
    expect(row.textContent).toContain("2");
    // A plain player with a password has no rights to list, and says so rather than leaving the cell empty.
    expect(row.textContent).toContain("Player");
    // Every interface language, each by its own name.
    const languages = within(screen.getByTestId("players-language")).getAllByRole("option");
    expect(languages.map((option) => option.textContent)).toEqual(["English", "Nederlands", "Français", "Deutsch", "Latviešu"]);

    fireEvent.change(screen.getByTestId("players-username"), { target: { value: "cy" } });
    fireEvent.change(screen.getByTestId("players-display-name"), { target: { value: "Cy" } });
    fireEvent.change(screen.getByTestId("players-language"), { target: { value: "lv" } });
    fireEvent.click(screen.getByTestId("players-add"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", "/api/accounts")).toEqual([{ username: "cy", display_name: "Cy", language: "lv" }]),
    );
    const shown = await screen.findByTestId("players-link");
    expect((within(shown).getByRole("textbox") as HTMLInputElement).value).toBe(link.url);
    expect(shown.textContent).toContain("Valid for 24 hours, once.");
    fireEvent.click(within(shown).getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(link.url));
    expect(await screen.findByTestId("players-row-acc_00000000000c")).toBeTruthy();
  });

  it("makes a reset link, and disables an account", async () => {
    let accounts = [ana];
    const fetchMock = stubFetch({
      "GET /api/me": () => json(200, organiserMe),
      "GET /api/accounts": () => json(200, accounts),
      [`POST /api/accounts/${ana.id}/reset-link`]: () => json(200, link),
      [`PUT /api/accounts/${ana.id}`]: () => {
        accounts = [{ ...ana, disabled: true }];
        return json(200, accounts[0]);
      },
    });
    renderPlayers();
    const row = await screen.findByTestId(`players-row-${ana.id}`);
    fireEvent.click(within(row).getByRole("button", { name: "Reset link" }));
    expect((within(await screen.findByTestId("players-link")).getByRole("textbox") as HTMLInputElement).value).toBe(link.url);

    fireEvent.click(within(row).getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `/api/accounts/${ana.id}`)).toEqual([{ disabled: true }]));
    expect(await within(row).findByRole("button", { name: "Enable" })).toBeTruthy();
  });

  it("lists the players who asked for a new password, to answer with a link or dismiss (DEL-268)", async () => {
    let accounts: (typeof ana & { reset_asked_at: string | null })[] = [
      { ...ana, reset_asked_at: "2026-10-28T09:00:00Z" },
      { ...bo, reset_asked_at: "2026-10-28T09:30:00Z" },
    ];
    const fetchMock = stubFetch({
      "GET /api/me": () => json(200, ownerMe),
      "GET /api/accounts": () => json(200, accounts),
      [`POST /api/accounts/${ana.id}/reset-link`]: () => {
        accounts = accounts.map((a) => (a.id === ana.id ? { ...a, reset_asked_at: null } : a));
        return json(200, link);
      },
      [`DELETE /api/accounts/${bo.id}/reset-request`]: () => {
        accounts = accounts.map((a) => (a.id === bo.id ? { ...a, reset_asked_at: null } : a));
        return new Response(null, { status: 204 });
      },
    });
    renderPlayers();
    const asked = await screen.findByTestId("players-resets");
    expect(within(asked).getByRole("heading").textContent).toBe("Asked for a new password (2)");
    fireEvent.click(within(screen.getByTestId(`players-reset-${ana.id}`)).getByRole("button", { name: "Reset link" }));
    expect((within(await screen.findByTestId("players-link")).getByRole("textbox") as HTMLInputElement).value).toBe(link.url);
    await waitFor(() => expect(screen.queryByTestId(`players-reset-${ana.id}`)).toBeNull());
    fireEvent.click(within(screen.getByTestId(`players-reset-${bo.id}`)).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByTestId("players-resets")).toBeNull());
    const dismissed = fetchMock.mock.calls.filter(
      ([path, init]) => path === `/api/accounts/${bo.id}/reset-request` && init?.method === "DELETE",
    );
    expect(dismissed).toHaveLength(1);
  });

  it("says what a request means once Delve sends email: no confirmed address, so hand the link over (DEL-314)", async () => {
    const asking = [{ ...ana, reset_asked_at: "2026-10-28T09:00:00Z" }];
    for (const enabled of [false, true]) {
      stubFetch({
        "GET /api/me": () => json(200, ownerMe),
        "GET /api/accounts": () => json(200, asking),
        "GET /api/mail/status": () => json(200, { enabled }),
      });
      renderPlayers();
      const asked = await screen.findByTestId("players-resets");
      if (enabled) {
        await waitFor(() => expect(asked.textContent).toContain("Delve couldn't email them a link"));
        expect(asked.textContent).not.toContain("Delve sends no mail");
      } else {
        expect(asked.textContent).toContain("Delve sends no mail");
      }
      cleanup();
      vi.unstubAllGlobals();
    }
  });

  it("only the owner sees Make organiser", async () => {
    stubFetch({ "GET /api/me": () => json(200, organiserMe), "GET /api/accounts": () => json(200, [ana, bo]) });
    renderPlayers();
    await screen.findByTestId(`players-row-${ana.id}`);
    expect(screen.queryByRole("button", { name: "Make organiser" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Withdraw organiser" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Make owner" })).toBeNull();
  });

  it("the owner makes and withdraws organisers and owners", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": () => json(200, ownerMe),
      "GET /api/accounts": () => json(200, [ana, bo]),
      [`PUT /api/accounts/${ana.id}`]: () => json(200, { ...ana, organiser: true }),
      [`PUT /api/accounts/${bo.id}`]: () => json(409, { error: "The last owner account can't lose its rights." }),
    });
    renderPlayers();
    const row = await screen.findByTestId(`players-row-${ana.id}`);
    fireEvent.click(within(row).getByRole("button", { name: "Make organiser" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `/api/accounts/${ana.id}`)).toEqual([{ organiser: true }]));

    const boRow = screen.getByTestId(`players-row-${bo.id}`);
    expect(within(boRow).getByRole("button", { name: "Withdraw organiser" })).toBeTruthy();
    fireEvent.click(within(boRow).getByRole("button", { name: "Make owner" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", `/api/accounts/${bo.id}`)).toEqual([{ owner: true }]));
    expect((await screen.findByRole("alert")).textContent).toBe("The last owner account can't lose its rights.");
  });

  it("opens sign-up, and lets a sign-up in or turns one away (DEL-156)", async () => {
    const cyra = { ...ana, id: "acc_00000000000c", username: "cyra", display_name: "Cyra", tables: 0, pending: true, request_note: "Bo's friend." };
    const dee = { ...cyra, id: "acc_00000000000d", username: "dee", display_name: "Dee", request_note: "" };
    let accounts = [ana, cyra, dee];
    let open = false;
    const fetchMock = stubFetch({
      "GET /api/me": () => json(200, organiserMe),
      "GET /api/accounts": () => json(200, accounts),
      "GET /api/sign-up": () => json(200, { open }),
      "PUT /api/sign-up": (init) => {
        open = (JSON.parse(String(init?.body)) as { open: boolean }).open;
        return json(200, { open });
      },
      [`POST /api/accounts/${cyra.id}/approve`]: () => {
        accounts = accounts.map((a) => (a.id === cyra.id ? { ...a, pending: false } : a));
        return json(200, { ...cyra, pending: false });
      },
      [`DELETE /api/accounts/${dee.id}`]: () => {
        accounts = accounts.filter((a) => a.id !== dee.id);
        return new Response(null, { status: 204 });
      },
    });
    renderPlayers();

    const box = (await screen.findByTestId("players-sign-up-open")) as HTMLInputElement;
    expect(box.checked).toBe(false);
    fireEvent.click(box);
    await waitFor(() => expect(sent(fetchMock, "PUT", "/api/sign-up")).toEqual([{ open: true }]));
    await waitFor(() => expect((screen.getByTestId("players-sign-up-open") as HTMLInputElement).checked).toBe(true));

    const waiting = await screen.findByTestId("players-waiting");
    expect(within(waiting).getByText("Waiting for approval (2)")).toBeTruthy();
    expect(within(waiting).getByText("Bo's friend.")).toBeTruthy();
    expect(screen.queryByTestId(`players-row-${cyra.id}`)).toBeNull();

    fireEvent.click(within(screen.getByTestId(`players-waiting-${cyra.id}`)).getByRole("button", { name: "Let in" }));
    expect(await screen.findByTestId(`players-row-${cyra.id}`)).toBeTruthy();

    fireEvent.click(within(screen.getByTestId(`players-waiting-${dee.id}`)).getByRole("button", { name: "Turn away" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Turn dee away?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Turn away" }));
    await waitFor(() => expect(screen.queryByTestId("players-waiting")).toBeNull());
    expect(fetchMock.mock.calls.some(([p, init]) => p === `/api/accounts/${dee.id}` && init?.method === "DELETE")).toBe(true);
  });
});
