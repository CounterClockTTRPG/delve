import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch } from "../play/testing";
import { renderArea } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Rulesets", () => {
  it("shows one card per ruleset, linking to it", async () => {
    stubFetch({
      "GET /api/rulesets": () =>
        json(200, [
          { id: "adnd2e", title: "AD&D 2nd Edition" },
          { id: "osric", title: "OSRIC" },
        ]),
    });
    renderArea("/rulesets");
    expect(await screen.findByRole("heading", { level: 1, name: "Rulesets" })).toBeTruthy();
    expect((await screen.findByRole("link", { name: /AD&D 2nd Edition/ })).getAttribute("href")).toBe("/rulesets/adnd2e");
    expect(screen.getByRole("link", { name: /OSRIC/ }).getAttribute("href")).toBe("/rulesets/osric");
  });

  it("says when there is no ruleset", async () => {
    stubFetch({ "GET /api/rulesets": () => json(200, []) });
    renderArea("/rulesets");
    expect(await screen.findByText("This install has no ruleset to look up.")).toBeTruthy();
  });

  it("says when the list can't be read", async () => {
    stubFetch({ "GET /api/rulesets": () => json(500, { error: "boom" }) });
    renderArea("/rulesets");
    expect(await screen.findByText("The rulesets couldn't be read: boom")).toBeTruthy();
  });

  it("speaks Dutch", async () => {
    stubFetch({ "GET /api/rulesets": () => json(200, [{ id: "adnd2e", title: "AD&D 2nd Edition" }]) });
    renderArea("/rulesets", "nl");
    expect(await screen.findByRole("heading", { level: 1, name: "Regelsystemen" })).toBeTruthy();
  });
});
