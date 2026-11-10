import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PartySidebar from "../play/PartySidebar";
import { base, character, json, party, renderWith, sent, stubFetch } from "../play/testing";
import CharacterSheet from "./CharacterSheet";

afterEach(() => {
  vi.unstubAllGlobals();
});

const ash = character("chr_00000000000a", "Ash");
const repaintPath = `${base}/characters/chr_00000000000a/portrait/repaint`;

describe("Repaint portrait (DEL-135)", () => {
  it("is on the sheet for whoever may repaint, and posts the repaint", async () => {
    const fetchMock = stubFetch({ [`POST ${repaintPath}`]: () => json(200, { image_id: "img_1", status: "painting" }) });
    const { unmount } = renderWith(<CharacterSheet character={ash} />);
    expect(screen.queryByRole("button", { name: "Repaint Ash's portrait" })).toBeNull();
    unmount();

    renderWith(<CharacterSheet character={ash} mayRepaint />);
    fireEvent.click(screen.getByRole("button", { name: "Repaint Ash's portrait" }));
    await waitFor(() => expect(sent(fetchMock, "POST", repaintPath)).toEqual([{}]));
  });

  it("says the server's reason when it is refused", async () => {
    stubFetch({
      [`POST ${repaintPath}`]: () =>
        json(422, { error: "Paid images are off for this campaign.", hint: "The host can turn paid images on." }),
    });
    renderWith(<CharacterSheet character={ash} mayRepaint />);
    fireEvent.click(screen.getByRole("button", { name: "Repaint Ash's portrait" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Paid images are off for this campaign. The host can turn paid images on.",
    );
  });

  it("shows the painting instead of the button while one is painted", () => {
    stubFetch({});
    renderWith(<CharacterSheet character={{ ...ash, portrait_painting: { provider: "replicate", queue: null } }} mayRepaint />);
    expect(screen.getByRole("status").textContent).toBe("The portrait is being painted…");
    expect(screen.queryByRole("button", { name: "Repaint Ash's portrait" })).toBeNull();
  });

  it("offers Try again for a portrait that failed, which repaints", async () => {
    const fetchMock = stubFetch({ [`POST ${repaintPath}`]: () => json(200, { image_id: "img_2", status: "painting" }) });
    renderWith(<CharacterSheet character={{ ...ash, portrait_failed: true }} mayRepaint />);
    expect(screen.getByText("The portrait couldn't be painted.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try Ash's portrait again" }));
    await waitFor(() => expect(sent(fetchMock, "POST", repaintPath)).toEqual([{}]));
  });

  it("is on the sheet only: the sidebar's card has no icon, and says when a portrait is painting", () => {
    const sheets = Object.fromEntries(party.map((m) => [m.id, character(m.id, m.name)]));
    sheets["chr_00000000000b"] = { ...sheets["chr_00000000000b"], portrait_painting: { provider: "x", queue: null } };
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={vi.fn()} sheets={sheets} />);
    expect(screen.queryByRole("button", { name: /Repaint .*'s portrait/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Try again/ })).toBeNull();
    expect(screen.getByText("The portrait is being painted…").getAttribute("role")).toBe("status");
  });
});
