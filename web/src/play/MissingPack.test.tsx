import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Play from "../routes/Play";
import MissingPack from "./MissingPack";
import { base, json, playRoutes, playState, renderWith, stubFetch } from "./testing";

afterEach(() => vi.unstubAllGlobals());

describe("a campaign whose pack isn't installed (DEL-307)", () => {
  it("names the ruleset or the setting it lacks", () => {
    const { unmount } = renderWith(<MissingPack kind="ruleset" id="adnd9" />);
    expect(screen.getByRole("alert").textContent).toBe("This campaign's ruleset, adnd9, isn't installed. Install its pack to play it.");
    unmount();
    renderWith(<MissingPack kind="setting" id="eberron" />);
    expect(screen.getByRole("alert").textContent).toContain("This campaign's setting, eberron, isn't installed.");
  });

  it("shows the notice on the play screen and no composer", async () => {
    const routes = playRoutes();
    routes[`GET ${base}/play/state`] = () => json(200, playState({ missing_pack: { kind: "ruleset", id: "adnd9" } }));
    stubFetch(routes);
    renderWith(<Play />);
    expect(await screen.findByTestId("missing-pack")).toBeTruthy();
    expect(screen.queryByTestId("composer")).toBeNull();
  });

  it("shows the composer when nothing is missing", async () => {
    stubFetch(playRoutes());
    renderWith(<Play />);
    expect(await screen.findByTestId("composer")).toBeTruthy();
    expect(screen.queryByTestId("missing-pack")).toBeNull();
  });
});
