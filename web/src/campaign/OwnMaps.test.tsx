import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, json, renderWith, stubFetch } from "../play/testing";
import OwnMaps from "./OwnMaps";

afterEach(() => {
  vi.unstubAllGlobals();
});

const slums = { campaign_id: CAMPAIGN, module_id: "mod_x", name: "slums", role: "map", is_default: false, own: true, updated_at: null, source: "" };

describe("OwnMaps", () => {
  it("lists the campaign's own maps, each opening the editor, and says they are never the module's", async () => {
    stubFetch({ [`GET ${base}/own-maps`]: () => json(200, [slums]) });
    renderWith(<OwnMaps campaignId={CAMPAIGN} />);
    const link = await screen.findByRole("link", { name: "slums" });
    expect(link.getAttribute("href")).toBe(`/campaigns/${CAMPAIGN}/own-maps/slums`);
    expect(screen.getByText(/not the module's/)).toBeTruthy();
  });

  it("makes a new map and opens it in the editor", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/own-maps`]: () => json(200, []),
      [`POST ${base}/own-maps`]: () => json(201, { ...slums, name: "market" }),
    });
    const { container } = renderWith(<OwnMaps campaignId={CAMPAIGN} />);
    fireEvent.change(await screen.findByLabelText("New map's name"), { target: { value: "market" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the map" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/own-maps` && init?.method === "POST")).toBe(true),
    );
    const posted = fetchMock.mock.calls.find(([p, init]) => p === `${base}/own-maps` && init?.method === "POST")!;
    expect(JSON.parse(posted[1]!.body as string)).toEqual({ name: "market" });
    expect(container).toBeTruthy();
  });

  it("shows why a map couldn't be made", async () => {
    stubFetch({
      [`GET ${base}/own-maps`]: () => json(200, []),
      [`POST ${base}/own-maps`]: () => json(409, { error: "The campaign already plays a map with this name." }),
    });
    renderWith(<OwnMaps campaignId={CAMPAIGN} />);
    fireEvent.change(await screen.findByLabelText("New map's name"), { target: { value: "crypt" } });
    fireEvent.click(screen.getByRole("button", { name: "Make the map" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already plays a map with this name");
  });

  it("deletes a map after asking", async () => {
    const fetchMock = stubFetch({
      [`GET ${base}/own-maps`]: () => json(200, [slums]),
      [`DELETE ${base}/own-maps/slums`]: () => new Response(null, { status: 204 }),
    });
    renderWith(<OwnMaps campaignId={CAMPAIGN} />);
    const row = (await screen.findByRole("link", { name: "slums" })).closest("li")!;
    fireEvent.click(within(row).getByRole("button", { name: "Delete" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/own-maps/slums` && init?.method === "DELETE")).toBe(true),
    );
  });
});
