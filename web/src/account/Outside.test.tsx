import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import AccountSection from "./AccountSection";
import Login from "./Login";
import SignUp from "./SignUp";

// Logging in, signing up and linking with Google (DEL-206): the buttons send the browser to Delve's start with what
// it needs, and the pages say what came back.

const ana = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };
const GOOGLE = [{ id: "google", title: "Google" }];
let assign: ReturnType<typeof vi.fn>;

beforeEach(() => {
  assign = vi.fn();
  at("/");
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function renderWith(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>{node}</DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

/** The page at `path`: jsdom's address (which `history.replaceState` changes, read as `document.location`), and a
 * `window.location` whose `assign` is a spy, since jsdom doesn't navigate. */
function at(path: string) {
  window.history.replaceState(null, "", path);
  const url = new URL(path, "http://localhost:3000");
  vi.stubGlobal("location", { assign, href: url.href, pathname: url.pathname, search: url.search, hash: url.hash });
}

describe("Continue with Google", () => {
  it("is offered on the login page only once a provider is", async () => {
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }), "GET /api/auth/providers": () => json(200, []) });
    renderWith(<Login onDone={vi.fn()} />);
    await screen.findByTestId("login-username");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByTestId("outside-google")).toBeNull();
  });

  it("sends the browser to the start, to come back to the page it was on", async () => {
    at("/play/cmp_1?seat=2");
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }), "GET /api/auth/providers": () => json(200, GOOGLE) });
    renderWith(<Login onDone={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Google" }));
    const url = new URL(assign.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/api/auth/google/start");
    expect(Object.fromEntries(url.searchParams)).toEqual({ mode: "login", next: "/play/cmp_1?seat=2" });
  });

  it("says what came back, once, and takes it off the address", async () => {
    at("/login?oidc=unknown");
    stubFetch({ "GET /api/me": () => json(401, { error: "Log in." }), "GET /api/auth/providers": () => json(200, GOOGLE) });
    renderWith(<Login onDone={vi.fn()} />);
    expect((await screen.findByTestId("outside-result")).textContent).toContain(
      "No Delve account is linked to that Google account.",
    );
    expect(document.location.search).toBe("");
  });

  it("signs up with the form's username and note, and no password", async () => {
    stubFetch({ "GET /api/sign-up": () => json(200, { open: true }), "GET /api/auth/providers": () => json(200, GOOGLE) });
    renderWith(<SignUp language="nl" />);
    const button = await screen.findByRole("button", { name: "Sign up with Google instead of a password" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("sign-up-username"), { target: { value: " cyra " } });
    fireEvent.change(screen.getByTestId("sign-up-note"), { target: { value: "Bo's friend" } });
    fireEvent.click(button);
    const url = new URL(assign.mock.calls[0][0], "http://x");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      mode: "signup",
      username: "cyra",
      note: "Bo's friend",
      language: "nl",
    });
  });

  it("a Google sign-up that came back waits for approval, as any sign-up", async () => {
    at("/sign-up?oidc=waiting&username=cyra");
    stubFetch({ "GET /api/sign-up": () => json(200, { open: true }), "GET /api/auth/providers": () => json(200, GOOGLE) });
    renderWith(<SignUp />);
    expect((await screen.findByTestId("sign-up-asked")).textContent).toContain("cyra");
  });

  it("a refused Google sign-up says why on the form", async () => {
    at("/sign-up?oidc=taken");
    stubFetch({ "GET /api/sign-up": () => json(200, { open: true }), "GET /api/auth/providers": () => json(200, GOOGLE) });
    renderWith(<SignUp />);
    expect((await screen.findByRole("alert")).textContent).toBe("That username is taken: choose another.");
  });
});

describe("Linked accounts", () => {
  const account = {
    "GET /api/account/sessions": () => json(200, []),
    "GET /api/auth/providers": () => json(200, GOOGLE),
  };

  it("offers to link Google, and lists it once linked with Unlink", async () => {
    let linked = true;
    const fetchMock = stubFetch({
      ...account,
      "GET /api/account/identities": () =>
        json(200, {
          identities: linked ? [{ provider: "google", title: "Google", email: "ana@example.org", linked_at: "" }] : [],
          has_password: true,
        }),
      "DELETE /api/account/identities/google": () => {
        linked = false;
        return new Response(null, { status: 204 });
      },
      "POST /api/auth/google/link": () => json(200, { url: "/api/auth/google/start?mode=link&ticket=t.k" }),
    });
    renderWith(<AccountSection account={ana} />);
    const row = await screen.findByTestId("account-identity-google");
    expect(row.textContent).toContain("ana@example.org");
    expect(screen.queryByRole("button", { name: "Link your Google account" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Unlink" }));
    expect(await screen.findByRole("button", { name: "Link your Google account" })).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path, init]) => path === "/api/account/identities/google" && init?.method === "DELETE")).toBe(
      true,
    );
    const link = screen.getByRole("button", { name: "Link your Google account" }) as HTMLButtonElement;
    expect(link.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Your password"), { target: { value: "correct horse battery" } });
    fireEvent.click(link);
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/api/auth/google/start?mode=link&ticket=t.k"));
    expect(sent(fetchMock, "POST", "/api/auth/google/link")).toEqual([{ password: "correct horse battery" }]);
  });

  it("says a refused unlink and what a link that came back said", async () => {
    at("/preferences?tab=profile&oidc=conflict");
    stubFetch({
      ...account,
      "GET /api/account/identities": () =>
        json(200, { identities: [{ provider: "google", title: "Google", email: "", linked_at: "" }], has_password: false }),
      "DELETE /api/account/identities/google": () => json(422, { error: "It is the only way you log in: set a password first." }),
    });
    renderWith(<AccountSection account={ana} />);
    expect((await screen.findByTestId("outside-result")).textContent).toBe(
      "That Google account is linked to another Delve account.",
    );
    expect(document.location.search).toBe("?tab=profile");
    fireEvent.click(await screen.findByRole("button", { name: "Unlink" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("It is the only way you log in: set a password first."),
    );
  });

  it("shows nothing while no provider is set up and nothing is linked", async () => {
    stubFetch({
      ...account,
      "GET /api/auth/providers": () => json(200, []),
      "GET /api/account/identities": () => json(200, { identities: [], has_password: true }),
    });
    renderWith(<AccountSection account={ana} />);
    await screen.findByRole("heading", { name: "Account" });
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByTestId("account-linked")).toBeNull();
  });
});

it("an account without a password links without one", async () => {
  stubFetch({
    "GET /api/account/sessions": () => json(200, []),
    "GET /api/auth/providers": () => json(200, GOOGLE),
    "GET /api/account/identities": () => json(200, { identities: [], has_password: false }),
    "POST /api/auth/google/link": () => json(200, { url: "/api/auth/google/start?mode=link&ticket=t.k" }),
  });
  renderWith(<AccountSection account={ana} />);
  fireEvent.click(await screen.findByRole("button", { name: "Link your Google account" }));
  expect(screen.queryByLabelText("Your password")).toBeNull();
  await waitFor(() => expect(assign).toHaveBeenCalledWith("/api/auth/google/start?mode=link&ticket=t.k"));
});
