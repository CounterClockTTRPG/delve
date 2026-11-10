import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import InvitePanel, { inviteUrl } from "./InvitePanel";
import { CAMPAIGN, base, json, renderWith, sent, stubFetch } from "./testing";

const toCanvas = vi.hoisted(() => vi.fn(async () => undefined));
vi.mock("qrcode", () => ({ default: { toCanvas }, toCanvas }));

const first = { url: "http://192.168.1.20:7810/join/tok-one", join_token: "tok-one" };
const second = { url: "http://192.168.1.20:7810/join/tok-two", join_token: "tok-two" };

beforeEach(() => {
  toCanvas.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("InvitePanel", () => {
  it("says the copy failed rather than Copied, when the clipboard refuses (DEL-174)", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn(async () => Promise.reject(new Error("denied"))) } });
    stubFetch({ [`GET ${base}/invite`]: () => json(200, first) });
    renderWith(<InvitePanel campaignId={CAMPAIGN} />);
    const link = (await screen.findByTestId("invite-url")) as HTMLInputElement;
    await waitFor(() => expect(link.value).toBe(first.url));
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    expect(await screen.findByText("Couldn't copy. Select it and copy it yourself.")).toBeTruthy();
    expect(screen.queryByText("Copied")).toBeNull();
  });

  it("shows the join link, copies it, draws its QR code, and makes a new one", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const fetchMock = stubFetch({
      [`GET ${base}/invite`]: () => json(200, first),
      [`POST ${base}/invite`]: () => json(200, second),
    });
    renderWith(<InvitePanel campaignId={CAMPAIGN} />);

    const link = (await screen.findByTestId("invite-url")) as HTMLInputElement;
    await waitFor(() => expect(link.value).toBe(first.url));
    await waitFor(() => expect(toCanvas).toHaveBeenCalledWith(expect.any(HTMLCanvasElement), first.url, expect.anything()));

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(first.url));
    expect(await screen.findByText("Copied")).toBeTruthy();

    // A new link asks first, since the old one stops working.
    fireEvent.click(screen.getByRole("button", { name: "New link" }));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Make a new link" }));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/invite`)).toEqual([{}]));
    await waitFor(() => expect(link.value).toBe(second.url));
    await waitFor(() => expect(toCanvas).toHaveBeenLastCalledWith(expect.any(HTMLCanvasElement), second.url, expect.anything()));
  });

  it("on loopback, says other devices need the LAN address that delve serve prints", async () => {
    stubFetch({ [`GET ${base}/invite`]: () => json(200, first) });
    renderWith(<InvitePanel campaignId={CAMPAIGN} />);
    const link = (await screen.findByTestId("invite-url")) as HTMLInputElement;
    await waitFor(() => expect(link.value).toBe(first.url));
    expect(screen.getByTestId("invite-loopback").textContent).toContain("delve serve");
  });

  it("uses the address the host's browser is on, when that isn't loopback", () => {
    expect(inviteUrl(first, new URL("http://delve.lan:7810/play/cmp_1"))).toEqual({ url: "http://delve.lan:7810/join/tok-one", loopback: false });
    expect(inviteUrl(first, new URL("http://192.168.1.30:7810/play/cmp_1")).url).toBe("http://192.168.1.30:7810/join/tok-one");
    for (const here of ["http://127.0.0.1:7810/", "http://localhost:7810/", "http://[::1]:7810/", "http://127.0.1.1:7810/"])
      expect(inviteUrl(first, new URL(here)), here).toEqual({ url: first.url, loopback: true });
  });

  it("says whoever opens the link makes an account or logs in", async () => {
    stubFetch({ [`GET ${base}/invite`]: () => json(200, first) });
    renderWith(<InvitePanel campaignId={CAMPAIGN} />);
    expect(await screen.findByText("Whoever opens the link makes an account or logs in, then takes a seat.")).toBeTruthy();
  });
});
