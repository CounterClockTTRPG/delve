import { screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch, type Handler } from "../play/testing";
import type { SettingInfo } from "./api";
import { renderArea, settingInfo } from "./testing";

const base = "/api/settings/oerth";
let routes: Record<string, Handler>;
let info: SettingInfo;

beforeEach(() => {
  info = settingInfo("oerth", "Oerth", { maps_in_use: "install" });
  routes = {
    [`GET ${base}`]: () => json(200, info),
    [`GET ${base}/world-maps`]: () =>
      json(200, [
        { name: "flanaess", title: "The Flanaess", status: "review", source: "picture", picture: true },
        { name: "wild-coast", title: "The Wild Coast", status: "ready", source: "geojson", picture: false },
      ]),
  };
  stubFetch(routes);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MapsTab", () => {
  it("lists the install's maps, each opening the editor, or its review while in review", async () => {
    renderArea("/settings/oerth?tab=maps");
    const flanaess = (await screen.findByText("The Flanaess")).closest("li")!;
    expect(within(flanaess).getByText("In review")).toBeTruthy();
    expect(within(flanaess).getByRole("link", { name: "Review" }).getAttribute("href")).toBe(
      "/world-maps/setting/oerth/flanaess/review",
    );
    const coast = screen.getByText("The Wild Coast").closest("li")!;
    expect(within(coast).getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(
      "/world-maps/setting/oerth/wild-coast",
    );
    expect(within(coast).queryByRole("link", { name: "Review" })).toBeNull();
    expect(await screen.findByRole("button", { name: "Import a world map" })).toBeTruthy();
    expect(screen.queryByText(/the built-in map/)).toBeNull();
  });

  it("names the built-in map new campaigns copy while the install has no ready map", async () => {
    info = settingInfo("oerth", "Oerth", {
      maps_in_use: "built-in",
      built_in_maps: [{ name: "flanaess", title: "The Flanaess (built in)" }],
    });
    renderArea("/settings/oerth?tab=maps");
    expect(
      await screen.findByText(
        "New campaigns copy The Flanaess (built in), the built-in map, until this install has a ready map of its own.",
      ),
    ).toBeTruthy();
  });

  it("says so when the install has no map", async () => {
    routes[`GET ${base}/world-maps`] = () => json(200, []);
    renderArea("/settings/oerth?tab=maps");
    expect(await screen.findByText("This install has no world map of this setting yet.")).toBeTruthy();
  });

  it("is a tab of the setting", async () => {
    renderArea("/settings/oerth");
    expect(await screen.findByRole("tab", { name: "Maps" })).toBeTruthy();
  });
});
