import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import AccountSection from "./AccountSection";

const FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0";
const SAFARI_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const account = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };
const here = { id: "lgn_00000000000a", device: FIREFOX_LINUX, last_used_at: new Date().toISOString(), current: true };
const phone = { id: "lgn_00000000000b", device: SAFARI_IPHONE, last_used_at: new Date(Date.now() - 3 * 86400_000).toISOString(), current: false };

const noContent = () => new Response(null, { status: 204 });

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSection() {
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <AccountSection account={account} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return assign;
}

describe("AccountSection", () => {
  it("changes the password", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/sessions": () => json(200, [here]),
      "PUT /api/account/password": noContent,
    });
    renderSection();
    expect(await screen.findByRole("heading", { level: 2, name: "Account" })).toBeTruthy();
    expect(screen.getByText("ana")).toBeTruthy();
    fireEvent.change(screen.getByTestId("account-old"), { target: { value: "correct horse battery" } });
    fireEvent.change(screen.getByTestId("account-new"), { target: { value: "staple battery horse" } });
    fireEvent.change(screen.getByTestId("account-new-again"), { target: { value: "staple battery hors" } });
    fireEvent.click(screen.getByTestId("account-password-save"));
    expect((await screen.findByRole("alert")).textContent).toBe("The passwords differ.");
    expect(sent(fetchMock, "PUT", "/api/account/password")).toEqual([]);

    fireEvent.change(screen.getByTestId("account-new-again"), { target: { value: "staple battery horse" } });
    fireEvent.click(screen.getByTestId("account-password-save"));
    expect(await screen.findByText("Your other devices are logged out.")).toBeTruthy();
    expect(sent(fetchMock, "PUT", "/api/account/password")).toEqual([
      { old: "correct horse battery", new: "staple battery horse" },
    ]);
    expect((screen.getByTestId("account-old") as HTMLInputElement).value).toBe("");
  });

  it("shows a wrong current password", async () => {
    stubFetch({
      "GET /api/account/sessions": () => json(200, [here]),
      "PUT /api/account/password": () => json(403, { error: "That isn't your current password." }),
    });
    renderSection();
    fireEvent.change(await screen.findByTestId("account-old"), { target: { value: "wrong" } });
    fireEvent.change(screen.getByTestId("account-new"), { target: { value: "staple battery horse" } });
    fireEvent.change(screen.getByTestId("account-new-again"), { target: { value: "staple battery horse" } });
    fireEvent.click(screen.getByTestId("account-password-save"));
    expect((await screen.findByRole("alert")).textContent).toBe("That isn't your current password.");
  });

  it("lists the logins and logs one out", async () => {
    let sessions = [here, phone];
    const fetchMock = stubFetch({
      "GET /api/account/sessions": () => json(200, sessions),
      [`DELETE /api/account/sessions/${phone.id}`]: () => {
        sessions = [here];
        return noContent();
      },
    });
    renderSection();
    const mine = await screen.findByTestId(`account-session-${here.id}`);
    expect(mine.textContent).toContain("Firefox on Linux");
    expect(mine.textContent).toContain("This device");
    const other = screen.getByTestId(`account-session-${phone.id}`);
    expect(other.textContent).toContain("Safari on iPhone");
    expect(other.textContent).toContain("3 days ago");
    expect(other.textContent).not.toContain("This device");

    fireEvent.click(within(other).getByRole("button", { name: "Log out" }));
    await waitFor(() => expect(screen.queryByTestId(`account-session-${phone.id}`)).toBeNull());
    expect(fetchMock.mock.calls.some(([p, init]) => p === `/api/account/sessions/${phone.id}` && init?.method === "DELETE")).toBe(true);
  });

  it("logs out everywhere after confirming", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/sessions": () => json(200, [here, phone]),
      "POST /api/account/sessions/end-all": noContent,
    });
    const assign = renderSection();
    fireEvent.click(await screen.findByTestId("account-end-all"));
    const dialog = await screen.findByRole("alertdialog");
    // Cancelled first: nothing happens.
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(sent(fetchMock, "POST", "/api/account/sessions/end-all")).toEqual([]);

    fireEvent.click(screen.getByTestId("account-end-all"));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Log out everywhere" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(sent(fetchMock, "POST", "/api/account/sessions/end-all")).toEqual([{}]);
  });

  it("logs this browser out", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/sessions": () => json(200, [here]),
      "POST /api/logout": noContent,
    });
    const assign = renderSection();
    fireEvent.click(await screen.findByTestId("account-logout"));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(sent(fetchMock, "POST", "/api/logout")).toEqual([{}]);
  });
});
