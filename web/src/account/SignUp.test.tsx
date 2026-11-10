import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import SignUp from "./SignUp";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PASSWORD = "correct horse battery";

function renderSignUp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <SignUp language="en" />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function fill(fields: Record<string, string>) {
  for (const [id, value] of Object.entries(fields)) fireEvent.change(screen.getByTestId(`sign-up-${id}`), { target: { value } });
}

describe("SignUp (DEL-156)", () => {
  it("says sign-up is closed while it is", async () => {
    stubFetch({ "GET /api/sign-up": () => json(200, { open: false }) });
    renderSignUp();
    expect((await screen.findByTestId("sign-up-closed")).textContent).toMatch(/closed/);
    expect(screen.queryByTestId("sign-up-username")).toBeNull();
  });

  it("asks for an account, which then waits for approval", async () => {
    const fetchMock = stubFetch({
      "GET /api/sign-up": () => json(200, { open: true }),
      "POST /api/sign-up": () => json(201, { username: "cyra", pending: true }),
    });
    renderSignUp();
    await screen.findByTestId("sign-up-username");
    fill({ username: " Cyra ", "display-name": "Cyra", password: PASSWORD, again: "not the same" });
    expect(screen.getByText("The two passwords differ.")).toBeTruthy();
    expect((screen.getByTestId("sign-up-submit") as HTMLButtonElement).disabled).toBe(true);
    fill({ again: PASSWORD, note: "Bo's friend." });
    fireEvent.click(screen.getByTestId("sign-up-submit"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", "/api/sign-up")).toEqual([
        { username: "Cyra", password: PASSWORD, language: "en", display_name: "Cyra", note: "Bo's friend." },
      ]),
    );
    expect((await screen.findByTestId("sign-up-asked")).textContent).toMatch(/cyra waits for approval/);
  });

  it("shows the server's refusal", async () => {
    stubFetch({
      "GET /api/sign-up": () => json(200, { open: true }),
      "POST /api/sign-up": () => json(409, { error: "That username is taken." }),
    });
    renderSignUp();
    await screen.findByTestId("sign-up-username");
    fill({ username: "ana", password: PASSWORD, again: PASSWORD });
    fireEvent.click(screen.getByTestId("sign-up-submit"));
    expect((await screen.findByRole("alert")).textContent).toBe("That username is taken.");
  });

  it("offers no address while mail is off", async () => {
    stubFetch({
      "GET /api/sign-up": () => json(200, { open: true }),
      "GET /api/mail/status": () => json(200, { enabled: false }),
    });
    renderSignUp();
    await screen.findByTestId("sign-up-username");
    expect(screen.queryByTestId("sign-up-email")).toBeNull();
  });

  it("offers an address while mail is on, and sends it", async () => {
    const fetchMock = stubFetch({
      "GET /api/sign-up": () => json(200, { open: true }),
      "GET /api/mail/status": () => json(200, { enabled: true }),
      "POST /api/sign-up": () => json(201, { username: "cyra", pending: true }),
    });
    renderSignUp();
    await screen.findByTestId("sign-up-email");
    fill({ username: "cyra", password: PASSWORD, again: PASSWORD, email: " cyra@example.org " });
    fireEvent.click(screen.getByTestId("sign-up-submit"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", "/api/sign-up")).toEqual([
        { username: "cyra", password: PASSWORD, language: "en", email: "cyra@example.org" },
      ]),
    );
    expect((await screen.findByTestId("sign-up-asked")).textContent).toMatch(/link to cyra@example.org/);
  });
});
