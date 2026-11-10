import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, sent, stubFetch } from "../play/testing";
import { ConfirmEmailRoot } from "./ConfirmEmail";
import EmailSection from "./EmailSection";
import { MailOffRoot } from "./MailOff";

const none = { email: null, pending: null, mail_host: true, mail_board: true };

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <EmailSection />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function renderAt(path: string, pattern: string, element: JSX.Element) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={pattern} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("EmailSection", () => {
  it("offers no address field while Delve sends no mail", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: false }),
      "GET /api/account/email": () => json(200, none),
    });
    renderSection();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/mail/status", expect.anything()));
    await act(() => new Promise((r) => setTimeout(r, 20)));
    expect(screen.queryByTestId("email-address")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Email" })).toBeNull();
  });

  it("sends a confirmation link to a typed address", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: true }),
      "GET /api/account/email": () => json(200, none),
      "PUT /api/account/email": () => json(202, { ...none, pending: "ana@example.org" }),
    });
    renderSection();
    expect(await screen.findByRole("heading", { level: 2, name: "Email" })).toBeTruthy();
    expect(screen.getByText("No address yet.")).toBeTruthy();
    fireEvent.change(screen.getByTestId("email-address"), { target: { value: "ana@example.org" } });
    fireEvent.click(screen.getByTestId("email-send"));
    await waitFor(() => expect(sent(fetchMock, "PUT", "/api/account/email")).toEqual([{ address: "ana@example.org" }]));
  });

  it("shows the address waiting for its link, and sends the link again", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: true }),
      "GET /api/account/email": () => json(200, { ...none, email: "old@example.org", pending: "new@example.org" }),
      "PUT /api/account/email": () => json(202, { ...none, email: "old@example.org", pending: "new@example.org" }),
    });
    renderSection();
    expect((await screen.findByTestId("email-current")).textContent).toContain("old@example.org");
    expect(screen.getByTestId("email-pending").textContent).toContain("new@example.org");
    fireEvent.click(screen.getByRole("button", { name: "Send the link again" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", "/api/account/email")).toEqual([{ address: "new@example.org" }]));
    expect(await screen.findByText("The link is on its way.")).toBeTruthy();
  });

  it("turns host mail and board mail off and on", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: true }),
      "GET /api/account/email": () => json(200, { ...none, email: "ana@example.org" }),
      "PUT /api/account/mail": () => json(200, { ...none, email: "ana@example.org", mail_board: false }),
    });
    renderSection();
    const host = (await screen.findByLabelText("Email from my hosts")) as HTMLInputElement;
    const board = screen.getByLabelText("Email about replies on the board") as HTMLInputElement;
    expect(host.checked && board.checked).toBe(true);
    fireEvent.click(board);
    await waitFor(() => expect(sent(fetchMock, "PUT", "/api/account/mail")).toEqual([{ mail_board: false }]));
  });

  it("removes the address", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/status": () => json(200, { enabled: true }),
      "GET /api/account/email": () => json(200, { ...none, email: "ana@example.org" }),
      "DELETE /api/account/email": () => new Response(null, { status: 204 }),
    });
    renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Remove the address" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([path, init]) => path === "/api/account/email" && init?.method === "DELETE")).toBe(true),
    );
  });
});

describe("ConfirmEmail", () => {
  it("confirms the address by its link", async () => {
    const fetchMock = stubFetch({
      "POST /api/account/email/confirm": () => json(200, { confirmed: true }),
    });
    renderAt("/account/email/tok-1", "/account/email/:token", <ConfirmEmailRoot />);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm the address" }));
    expect(await screen.findByText("Your address is confirmed.")).toBeTruthy();
    expect(sent(fetchMock, "POST", "/api/account/email/confirm")).toEqual([{ token: "tok-1" }]);
  });

  it("says a used link doesn't work", async () => {
    stubFetch({
      "POST /api/account/email/confirm": () => json(404, { error: "This link has expired or was used." }),
    });
    renderAt("/account/email/tok-1", "/account/email/:token", <ConfirmEmailRoot />);
    fireEvent.click(await screen.findByRole("button", { name: "Confirm the address" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "This link has expired or was used: send a new one from Preferences.",
    );
  });
});

describe("MailOff", () => {
  it("turns that mail off", async () => {
    const fetchMock = stubFetch({
      "GET /api/mail/off/off-1": () => json(200, { group: "board" }),
      "POST /api/mail/off/off-1": () => json(200, { group: "board" }),
    });
    renderAt("/mail/off/off-1", "/mail/off/:token", <MailOffRoot />);
    expect(await screen.findByText("Stop email about replies on the board?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn it off" }));
    expect(await screen.findByText(/No more email about replies on the board/)).toBeTruthy();
    expect(fetchMock.mock.calls.some(([path, init]) => path === "/api/mail/off/off-1" && init?.method === "POST")).toBe(true);
  });

  it("says a link Delve didn't make doesn't work", async () => {
    stubFetch({ "GET /api/mail/off/bad": () => json(404, { error: "This link doesn't work." }) });
    renderAt("/mail/off/bad", "/mail/off/:token", <MailOffRoot />);
    expect((await screen.findByRole("alert")).textContent).toBe("This link doesn't work.");
  });
});
