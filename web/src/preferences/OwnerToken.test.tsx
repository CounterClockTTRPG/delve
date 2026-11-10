import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import OwnerToken from "./OwnerToken";

const NEW = "f00dfeed";
const LINKS = [`http://192.168.1.20:7810/#token=${NEW}`, `http://localhost:7810/#token=${NEW}`];

let fetchMock: ReturnType<typeof vi.fn>;
let answer: () => Response;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  answer = () => json(200, { token: NEW, links: LINKS });
  fetchMock = vi.fn(async () => answer());
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderOwnerToken() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <OwnerToken />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

async function makeNew() {
  fireEvent.click(screen.getByRole("button", { name: "Make a new owner token" }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Make" }));
}

// DEL-154, audit finding 9: the owner makes a new owner token from Preferences, and sees its links once.
describe("OwnerToken", () => {
  it("asks nothing until the owner makes a new token", () => {
    renderOwnerToken();
    expect(screen.getByRole("heading", { level: 2, name: "Owner token" })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("makes a new token after the owner confirms, and shows its links", async () => {
    renderOwnerToken();
    await makeNew();
    expect(await screen.findByText(LINKS[0])).toBeTruthy();
    expect(screen.getByText(LINKS[1])).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/owner-token/new", expect.objectContaining({ method: "POST" }));
    expect(screen.getByRole("status").textContent).toContain("The old token and its links no longer work");
  });

  it("does nothing when the owner cancels", async () => {
    renderOwnerToken();
    fireEvent.click(screen.getByRole("button", { name: "Make a new owner token" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the links once: hidden again on Done", async () => {
    renderOwnerToken();
    await makeNew();
    fireEvent.click(await screen.findByRole("button", { name: "Done" }));
    expect(screen.queryByText(LINKS[0])).toBeNull();
  });

  it("says why it failed", async () => {
    answer = () => json(403, { error: "Only the install's owner can do this." });
    renderOwnerToken();
    await makeNew();
    expect((await screen.findByRole("alert")).textContent).toBe("No new token: Only the install's owner can do this.");
  });
});
