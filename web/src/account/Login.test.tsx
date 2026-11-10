import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import Login from "./Login";

const ana = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderLogin(onDone = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <Login onDone={onDone} />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return onDone;
}

function logIn(username: string, password: string) {
  fireEvent.change(screen.getByTestId("login-username"), { target: { value: username } });
  fireEvent.change(screen.getByTestId("login-password"), { target: { value: password } });
  fireEvent.click(screen.getByTestId("login-submit"));
}

describe("Login", () => {
  it("logs in and reloads", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "POST /api/login": () => json(200, { account: ana }),
    });
    const done = renderLogin();
    expect(await screen.findByRole("heading", { level: 1, name: "Log in to Delve" })).toBeTruthy();
    logIn(" ana ", "correct horse battery");
    await waitFor(() => expect(done).toHaveBeenCalled());
    // The username goes as typed: the server folds it.
    expect(sent(fetchMock, "POST", "/api/login")).toEqual([{ username: " ana ", password: "correct horse battery" }]);
  });

  it("shows the server's refusal", async () => {
    stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "POST /api/login": () => json(401, { error: "Wrong username or password." }),
    });
    const done = renderLogin();
    await screen.findByTestId("login-username");
    logIn("ana", "wrong");
    expect((await screen.findByRole("alert")).textContent).toBe("Wrong username or password.");
    expect(done).not.toHaveBeenCalled();
    expect((screen.getByTestId("login-password") as HTMLInputElement).value).toBe("");
  });

  it("never asks for the owner token", async () => {
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in to Delve." }) });
    renderLogin();
    await screen.findByTestId("login-username");
    expect(screen.queryByText(/token/i)).toBeNull();
    expect(screen.queryByTestId("login-first-owner")).toBeNull();
  });

  it("offers the first owner account on this machine, while there is none", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": () =>
        json(200, { principal: { id: "owner", roles: ["organiser"] }, account: null, seat: null, keepable_seat: null, owner_account_exists: false }),
      "POST /api/accounts/first-owner": () => json(201, { account: { ...ana, username: "olga", owner: true, organiser: true } }),
    });
    const done = renderLogin();
    const first = await screen.findByTestId("login-first-owner");
    expect(first.textContent).toContain("Make the owner account");
    fireEvent.change(screen.getByTestId("first-owner-username"), { target: { value: "olga" } });
    fireEvent.change(screen.getByTestId("first-owner-password"), { target: { value: "correct horse battery" } });
    fireEvent.click(screen.getByTestId("first-owner-submit"));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(sent(fetchMock, "POST", "/api/accounts/first-owner")).toEqual([
      { username: "olga", password: "correct horse battery" },
    ]);
  });

  it("offers nothing more once the owner account exists", async () => {
    stubFetch({
      "GET /api/me": () =>
        json(200, { principal: { id: "owner", roles: ["organiser"] }, account: null, seat: null, keepable_seat: null, owner_account_exists: true }),
    });
    renderLogin();
    await screen.findByTestId("login-username");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("login-first-owner")).toBeNull();
  });

  it("offers to ask for an account while sign-up is open (DEL-156)", async () => {
    stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "GET /api/sign-up": () => json(200, { open: true }),
    });
    renderLogin();
    expect((await screen.findByTestId("login-sign-up")).getAttribute("href")).toBe("/sign-up");
  });

  it("offers no sign-up while it is closed", async () => {
    stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "GET /api/sign-up": () => json(200, { open: false }),
    });
    renderLogin();
    expect(await screen.findByRole("heading", { level: 1, name: "Log in to Delve" })).toBeTruthy();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("login-sign-up")).toBeNull();
  });

  it("asks the owner for a new password, the same whatever the username (DEL-268)", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "GET /api/auth/providers": () => json(200, []),
      "POST /api/password-help": () => json(202, { asked: true }),
    });
    renderLogin();
    fireEvent.click(await screen.findByTestId("forgot-open"));
    expect(screen.getByTestId("forgot").textContent).toContain("Delve sends no mail");
    expect((screen.getByTestId("forgot-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("forgot-submit").textContent).toBe("Ask the owner");
    fireEvent.change(screen.getByTestId("forgot-username"), { target: { value: " ana " } });
    fireEvent.click(screen.getByTestId("forgot-submit"));
    expect((await screen.findByTestId("forgot-asked")).textContent).toContain("When the owner gives you a link");
    expect(sent(fetchMock, "POST", "/api/password-help")).toEqual([{ username: "ana" }]);
  });

  it("mails a link to a confirmed address while Delve sends email, the username or the address (DEL-314)", async () => {
    const fetchMock = stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "GET /api/auth/providers": () => json(200, []),
      "GET /api/mail/status": () => json(200, { enabled: true }),
      "POST /api/password-help": () => json(202, { asked: true }),
    });
    renderLogin();
    fireEvent.click(await screen.findByTestId("forgot-open"));
    await waitFor(() => expect(screen.getByTestId("forgot").textContent).toContain("Give your username or your email address"));
    expect(screen.getByTestId("forgot").textContent).not.toContain("Delve sends no mail");
    expect(screen.getByLabelText("Username or email address")).toBe(screen.getByTestId("forgot-username"));
    expect(screen.getByTestId("forgot-submit").textContent).toBe("Send me a link");
    fireEvent.change(screen.getByTestId("forgot-username"), { target: { value: " ana@example.org " } });
    fireEvent.click(screen.getByTestId("forgot-submit"));
    expect((await screen.findByTestId("forgot-asked")).textContent).toContain("a link is on its way");
    expect(sent(fetchMock, "POST", "/api/password-help")).toEqual([{ username: "ana@example.org" }]);
  });

  it("points to an outside login when one is set up (DEL-268)", async () => {
    stubFetch({
      "GET /api/me": () => json(401, { error: "Log in to Delve." }),
      "GET /api/auth/providers": () => json(200, [{ id: "google", title: "Google" }]),
    });
    renderLogin();
    fireEvent.click(await screen.findByTestId("forgot-open"));
    expect((await screen.findByText(/If you linked Google to your account/)).textContent).toContain("password or not");
  });
});
