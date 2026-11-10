import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CAMPAIGN, base, json, renderWith, stubFetch } from "../play/testing";
import WorldMaps from "./WorldMaps";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ROWS = [
  { name: "vale", title: "The Vale", status: "ready", source: "module", picture: false },
  { name: "flanaess", title: "The Flanaess", status: "review", source: "campaign", picture: true },
];

function routes() {
  return {
    [`GET ${base}/organiser/world-maps`]: () => json(200, ROWS),
    [`DELETE ${base}/world-maps/vale`]: () => new Response(null, { status: 204 }),
  };
}

const row = async (title: string) => (await screen.findByText(title)).closest("li")!;

describe("WorldMaps", () => {
  it("lists the campaign's maps from the organiser's list, those in review marked", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<WorldMaps campaignId={CAMPAIGN} />);
    const flanaess = await row("The Flanaess");
    expect(within(flanaess).getByText("In review")).toBeTruthy();
    expect(within(await row("The Vale")).queryByText("In review")).toBeNull();
    expect(fetchMock.mock.calls.some(([p]) => p === `${base}/world-maps`)).toBe(false);
    // The DSL text area is gone.
    expect(screen.queryByLabelText("Map text")).toBeNull();
  });

  it("offers Edit, Review, the picture and Delete, as each map allows", async () => {
    stubFetch(routes());
    renderWith(<WorldMaps campaignId={CAMPAIGN} />);
    const flanaess = await row("The Flanaess");
    expect(within(flanaess).getByRole("link", { name: "Review" }).getAttribute("href")).toBe(
      `/world-maps/campaign/${CAMPAIGN}/flanaess/review`,
    );
    expect(within(flanaess).getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(
      `/world-maps/campaign/${CAMPAIGN}/flanaess`,
    );
    expect(within(flanaess).getByRole("link", { name: "Download the picture" }).getAttribute("href")).toBe(
      `${base}/world-maps/flanaess/picture`,
    );
    // Start knowledge waits for the review; a map in review isn't played.
    expect(within(flanaess).queryByRole("button", { name: "What the party knows at the start" })).toBeNull();

    const vale = await row("The Vale");
    expect(within(vale).queryByRole("link", { name: "Review" })).toBeNull();
    expect(within(vale).queryByRole("link", { name: "Download the picture" })).toBeNull();
    expect(await within(vale).findByRole("button", { name: "What the party knows at the start" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "Import a world map" })).toBeTruthy();
  });

  it("deletes a map after asking", async () => {
    const fetchMock = stubFetch(routes());
    renderWith(<WorldMaps campaignId={CAMPAIGN} />);
    fireEvent.click(within(await row("The Vale")).getByRole("button", { name: "Delete" }));
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([p, init]) => p === `${base}/world-maps/vale` && init?.method === "DELETE")).toBe(true),
    );
  });
});
