import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch } from "../play/testing";
import { renderArea } from "../setting/testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Settings", () => {
  it("lists the settings with a link to each", async () => {
    stubFetch({ "GET /api/settings": () => json(200, [{ id: "greyhawk", title: "Greyhawk" }]) });
    renderArea("/settings");
    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeTruthy();
    const link = await screen.findByRole("link", { name: "Greyhawk" });
    expect(link.getAttribute("href")).toBe("/settings/greyhawk");
  });

  it("says when there is no setting", async () => {
    stubFetch({ "GET /api/settings": () => json(200, []) });
    renderArea("/settings");
    expect(await screen.findByText("This install has no setting.")).toBeTruthy();
  });

  it("says when the list can't be read", async () => {
    stubFetch({ "GET /api/settings": () => json(500, { error: "boom" }) });
    renderArea("/settings");
    expect(await screen.findByText("The settings couldn't be read: boom")).toBeTruthy();
  });
});
