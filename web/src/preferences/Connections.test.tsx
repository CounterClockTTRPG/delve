import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import Connections from "./Connections";
import type { ConnectionsState } from "./connections";

const TOKEN = "tok-SECRET-XYZZY";

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;
let state: ConnectionsState;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function bodies(method: string, path: string): unknown[] {
  return fetchMock.mock.calls
    .filter(([p, init]) => p === path && init?.method === method)
    .map(([, init]) => (init.body === undefined ? undefined : JSON.parse(String(init.body))));
}

beforeEach(() => {
  state = { replicate: { state: "unset" }, assetgen: { url: null, token: "unset" } };
  routes = { "GET /api/connections": () => json(200, state) };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderConnections() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <Connections />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

const replicate = () => screen.getByRole("group", { name: "Replicate" });
const assetgen = () => screen.getByRole("group", { name: "assetgen" });

describe("Connections", () => {
  it("shows the owner the two connections", async () => {
    renderConnections();
    expect(await screen.findByRole("heading", { level: 2, name: "Connections" })).toBeTruthy();
    expect(replicate()).toBeTruthy();
    expect(assetgen()).toBeTruthy();
  });

  it("is hidden from a seat, which the server answers 403", async () => {
    routes["GET /api/connections"] = () => json(403, { error: "Only the install's owner can do this." });
    const { container } = renderConnections();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/connections", expect.anything()));
    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(screen.queryByText("Only the install's owner can do this.")).toBeNull();
  });

  it.each([
    ["unset", "Token: Not set"],
    ["set", "Token: Set"],
    ["environment", "Token: From the environment"],
  ] as const)("says the Replicate token is %s", async (stored, shown) => {
    state.replicate = { state: stored };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    expect(within(replicate()).getByText(shown)).toBeTruthy();
  });

  it("takes the Replicate token in a password field, and empties it after saving", async () => {
    routes["PUT /api/connections/replicate"] = () => {
      state.replicate = { state: "set" };
      return json(200, state.replicate);
    };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    const field = within(replicate()).getByLabelText("Token") as HTMLInputElement;
    expect(field.type).toBe("password");

    fireEvent.change(field, { target: { value: TOKEN } });
    fireEvent.click(within(replicate()).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(within(replicate()).getByText("Token: Set")).toBeTruthy());
    expect(bodies("PUT", "/api/connections/replicate")).toEqual([{ token: TOKEN }]);
    expect(field.value).toBe("");
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("doesn't send an empty token", async () => {
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    expect((within(replicate()).getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows why a token was refused", async () => {
    routes["PUT /api/connections/replicate"] = () => json(422, { error: "A token is one word." });
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    fireEvent.change(within(replicate()).getByLabelText("Token"), { target: { value: "two words" } });
    fireEvent.click(within(replicate()).getByRole("button", { name: "Save" }));
    expect(await within(replicate()).findByText("Not saved: A token is one word.")).toBeTruthy();
  });

  it("asks before removing the Replicate token", async () => {
    state.replicate = { state: "set" };
    routes["DELETE /api/connections/replicate"] = () => {
      state.replicate = { state: "unset" };
      return json(200, state.replicate);
    };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });

    fireEvent.click(within(replicate()).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Remove the Replicate token?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(bodies("DELETE", "/api/connections/replicate")).toEqual([]);

    fireEvent.click(within(replicate()).getByRole("button", { name: "Remove" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(within(replicate()).getByText("Token: Not set")).toBeTruthy());
    expect(bodies("DELETE", "/api/connections/replicate")).toHaveLength(1);
  });

  it("offers no Remove for a token from the environment", async () => {
    state.replicate = { state: "environment" };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    expect(within(replicate()).queryByRole("button", { name: "Remove" })).toBeNull();
  });

  it("starts assetgen's URL at localhost:8765, with an optional token", async () => {
    let answer: unknown;
    routes["PUT /api/connections/assetgen"] = (init) => {
      answer = JSON.parse(String(init?.body));
      state.assetgen = { url: "http://localhost:8765", token: "unset" };
      return json(200, state.assetgen);
    };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    const url = within(assetgen()).getByLabelText("URL") as HTMLInputElement;
    const token = within(assetgen()).getByLabelText("Token (optional)") as HTMLInputElement;
    expect(url.value).toBe("http://localhost:8765");
    expect(token.type).toBe("password");
    expect(token.required).toBe(false);

    fireEvent.click(within(assetgen()).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(answer).toEqual({ url: "http://localhost:8765" }));
    expect(await within(assetgen()).findByText("Saved")).toBeTruthy();
  });

  it("keeps assetgen's stored URL, and sends a token only when one is typed", async () => {
    state.assetgen = { url: "http://192.168.1.20:8765", token: "set" };
    routes["PUT /api/connections/assetgen"] = () => json(200, state.assetgen);
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    expect((within(assetgen()).getByLabelText("URL") as HTMLInputElement).value).toBe("http://192.168.1.20:8765");
    expect(within(assetgen()).getByText("Token: Set")).toBeTruthy();

    const token = within(assetgen()).getByLabelText("Token (optional)") as HTMLInputElement;
    fireEvent.change(token, { target: { value: TOKEN } });
    fireEvent.click(within(assetgen()).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(bodies("PUT", "/api/connections/assetgen")).toEqual([{ url: "http://192.168.1.20:8765", token: TOKEN }]),
    );
    await waitFor(() => expect(token.value).toBe(""));
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("asks before removing assetgen", async () => {
    state.assetgen = { url: "http://localhost:8765", token: "unset" };
    routes["DELETE /api/connections/assetgen"] = () => json(200, { url: null, token: "unset" });
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    fireEvent.click(within(assetgen()).getByRole("button", { name: "Remove" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Remove the assetgen connection?")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(bodies("DELETE", "/api/connections/assetgen")).toHaveLength(1));
  });

  it.each([
    ["replicate", "Replicate", { ok: false, message: "Replicate refused the token (HTTP 401)." }],
    ["assetgen", "assetgen", { ok: true, message: "assetgen answered, with 3 image models." }],
  ] as const)("Test shows %s's answer", async (name, label, answer) => {
    routes[`POST /api/connections/${name}/test`] = () => json(200, answer);
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    const group = screen.getByRole("group", { name: label });
    fireEvent.click(within(group).getByRole("button", { name: "Test" }));
    expect(await within(group).findByText(answer.message)).toBeTruthy();
  });
});

describe("Google login (DEL-206)", () => {
  const URIS = ["https://delve.example/api/auth/google/callback", "http://localhost:7810/api/auth/google/callback"];
  const google = () => screen.getByRole("group", { name: "Google login" });

  it("shows the redirect URIs to register, takes the secret in a password field, and never shows it", async () => {
    state.google = { client_id: null, secret: "unset", redirect_uris: URIS };
    routes["PUT /api/connections/google"] = () => {
      state.google = { client_id: "id-1.apps", secret: "set", redirect_uris: URIS };
      return json(200, state.google);
    };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    expect(within(google()).getByTestId("google-redirects").textContent).toContain(URIS[0]);
    // Nothing to test without someone logging in.
    expect(within(google()).queryByRole("button", { name: "Test" })).toBeNull();
    const save = within(google()).getByRole("button", { name: "Save" }) as HTMLButtonElement;
    fireEvent.change(within(google()).getByLabelText("Client ID"), { target: { value: " id-1.apps " } });
    expect(save.disabled).toBe(true);
    const secret = within(google()).getByLabelText("Client secret") as HTMLInputElement;
    expect(secret.type).toBe("password");
    fireEvent.change(secret, { target: { value: "GOCSPX-SECRET" } });
    fireEvent.click(save);
    await waitFor(() => expect(bodies("PUT", "/api/connections/google")).toEqual([{ client_id: "id-1.apps", client_secret: "GOCSPX-SECRET" }]));
    await waitFor(() => expect(secret.value).toBe(""));
    expect(document.body.innerHTML).not.toContain("GOCSPX-SECRET");
  });

  it("keeps the stored secret when only the client id changes", async () => {
    state.google = { client_id: "id-1.apps", secret: "set", redirect_uris: URIS };
    routes["PUT /api/connections/google"] = () => json(200, { ...state.google, client_id: "id-2.apps" });
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    fireEvent.change(within(google()).getByLabelText("Client ID"), { target: { value: "id-2.apps" } });
    fireEvent.click(within(google()).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(bodies("PUT", "/api/connections/google")).toEqual([{ client_id: "id-2.apps" }]));
  });
});

describe("Email (DEL-314)", () => {
  const email = () => screen.getByRole("group", { name: "Email" });
  const unset = {
    provider: "log" as const,
    sender: "",
    public_url: "",
    public_url_default: "https://delve.example",
    key: "unset" as const,
    sent_today: 0,
    waiting: 0,
    failures: [],
  };

  it("saves the provider, the sender and the key, and never shows the key", async () => {
    state.email = unset;
    routes["PUT /api/connections/email"] = () => {
      state.email = { ...unset, provider: "emailit", sender: "Delve <d@example.org>", key: "set" };
      return json(200, state.email);
    };
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    fireEvent.change(within(email()).getByLabelText("Sends through"), { target: { value: "emailit" } });
    fireEvent.change(within(email()).getByLabelText("Sender"), { target: { value: " Delve <d@example.org> " } });
    const key = within(email()).getByLabelText("Emailit key") as HTMLInputElement;
    expect(key.type).toBe("password");
    fireEvent.change(key, { target: { value: "em_SECRET" } });
    fireEvent.click(within(email()).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(bodies("PUT", "/api/connections/email")).toEqual([
        { provider: "emailit", sender: "Delve <d@example.org>", public_url: "", key: "em_SECRET" },
      ]),
    );
    await waitFor(() => expect(key.value).toBe(""));
    expect(await within(email()).findByText("Token: Set")).toBeTruthy();
    expect(document.body.innerHTML).not.toContain("em_SECRET");
  });

  it("keeps the stored key when the field is left empty", async () => {
    state.email = { ...unset, provider: "emailit", sender: "d@example.org", key: "set" };
    routes["PUT /api/connections/email"] = () => json(200, state.email);
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    fireEvent.click(within(email()).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(bodies("PUT", "/api/connections/email")).toEqual([
        { provider: "emailit", sender: "d@example.org", public_url: "" },
      ]),
    );
  });

  it("shows the Test message, today's count, what waits and the latest failures at the reader's time", async () => {
    const at = "2026-10-30T10:00:00+00:00";
    state.email = {
      ...unset,
      sent_today: 4,
      waiting: 2,
      failures: [{ kind: "board", at, failure: "Emailit refused it (HTTP 422)" }],
    };
    const answer = { ok: true, message: "A test email is on its way to your confirmed address." };
    routes["POST /api/connections/email/test"] = () => json(200, answer);
    renderConnections();
    await screen.findByRole("heading", { name: "Connections" });
    expect(within(email()).getByText("Sent today: 4")).toBeTruthy();
    expect(within(email()).getByText("Waiting to go: 2")).toBeTruthy();
    const failure = within(email()).getByText(/Emailit refused it/);
    expect(failure.textContent).toContain(new Date(at).toLocaleString("en"));
    expect(failure.textContent, "no raw ISO time").not.toContain(at);
    expect(failure.querySelector("time")?.getAttribute("datetime")).toBe(at);
    fireEvent.click(within(email()).getByRole("button", { name: "Test" }));
    expect(await within(email()).findByText(answer.message)).toBeTruthy();
  });
});
