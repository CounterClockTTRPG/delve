import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { HelpPanel } from "./HelpPanel";
import { TourProvider, toursFor } from "./tour";

// jsdom lays nothing out: every element is given a box, so the tour finds its parts.
beforeEach(() => {
  localStorage.clear();
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    top: 100, left: 100, width: 120, height: 30, right: 220, bottom: 130, x: 100, y: 100, toJSON: () => ({}),
  } as DOMRect);
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.restoreAllMocks());

/** A player's Preferences: Profile and This browser, and none of the organiser's tabs. */
function PlayerPreferences() {
  return (
    <div role="tablist">
      <button type="button" role="tab" id="preferences-tab-profile">Profile</button>
      <button type="button" role="tab" id="preferences-tab-browser">This browser</button>
    </div>
  );
}

function at(path: string, role: "player" | "organiser" | "owner" = "player") {
  return render(
    <I18nProvider language="en">
      <MemoryRouter initialEntries={[path]}>
        <TourProvider role={role}>
          <Routes>
            <Route path="/preferences" element={<PlayerPreferences />} />
            <Route path="*" element={<p>Elsewhere</p>} />
          </Routes>
          <HelpPanel role={role} place="nav" />
        </TourProvider>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("guided tours", () => {
  it("are each for their screen and their readers", () => {
    expect(toursFor("/play/cmp_1", "player").map((t) => t.id)).toEqual(["play"]);
    expect(toursFor("/campaigns/cmp_1", "player")).toEqual([]);
    expect(toursFor("/campaigns/cmp_1", "organiser").map((t) => t.id)).toEqual(["campaign"]);
    expect(toursFor("/campaigns", "owner").map((t) => t.id)).toEqual(["new-campaign"]);
  });

  it("offers a screen's tour once, then walks its parts on the screen with Next and Back", async () => {
    at("/preferences");
    const offer = await screen.findByRole("region", { name: "A tour of this screen" }, { timeout: 2000 });
    fireEvent.click(within(offer).getByRole("button", { name: "Show me" }));
    const card = screen.getByRole("dialog", { name: "Profile" });
    // Only the tabs a player has: Backends and the others aren't on the screen.
    expect(within(card).getByText("Preferences: 1 of 2")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "This browser" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("dialog", { name: "Profile" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByTestId("tour")).toBeNull();
    expect(localStorage.getItem("delve.tour.preferences")).toBe("1");
  });

  it("doesn't offer a tour this browser has seen, and plays it again from the help panel", async () => {
    localStorage.setItem("delve.tour.preferences", "1");
    at("/preferences");
    await act(() => new Promise((resolve) => setTimeout(resolve, 700)));
    expect(screen.queryByTestId("tour-offer")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    fireEvent.click(screen.getByRole("button", { name: "Take the tour: Preferences" }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Profile" })).toBeTruthy());
  });

  it("ends on Escape or Skip the tour", async () => {
    at("/preferences");
    fireEvent.click(await screen.findByRole("button", { name: "Show me" }, { timeout: 2000 }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("tour")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    fireEvent.click(screen.getByRole("button", { name: "Take the tour: Preferences" }));
    fireEvent.click(await screen.findByRole("button", { name: "Skip the tour" }));
    expect(screen.queryByTestId("tour")).toBeNull();
  });

  it("offers nothing on a screen without a tour, and Not now keeps it from coming back", async () => {
    const first = at("/somewhere");
    await act(() => new Promise((resolve) => setTimeout(resolve, 700)));
    expect(screen.queryByTestId("tour-offer")).toBeNull();
    first.unmount();
    at("/preferences");
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }, { timeout: 2000 }));
    expect(screen.queryByTestId("tour-offer")).toBeNull();
    expect(localStorage.getItem("delve.tour.preferences")).toBe("1");
  });

  it("once one offer is answered, no other screen offers its tour (DEL-267)", async () => {
    const first = at("/preferences");
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }, { timeout: 2000 }));
    expect(localStorage.getItem("delve.tours.answered")).toBe("1");
    first.unmount();
    // As if another screen's tour: this one's own mark gone, the answer kept.
    localStorage.removeItem("delve.tour.preferences");
    at("/preferences");
    await act(() => new Promise((resolve) => setTimeout(resolve, 700)));
    expect(screen.queryByTestId("tour-offer")).toBeNull();
  });

  it("Skip the tours offers no tour again in this browser, and Help still plays one (DEL-211)", async () => {
    const first = at("/preferences");
    fireEvent.click(await screen.findByRole("button", { name: "Skip the tours" }, { timeout: 2000 }));
    expect(screen.queryByTestId("tour-offer")).toBeNull();
    expect(localStorage.getItem("delve.tours.skipped")).toBe("1");
    first.unmount();
    at("/preferences");
    await act(() => new Promise((resolve) => setTimeout(resolve, 700)));
    expect(screen.queryByTestId("tour-offer"), "no tour is offered again").toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    fireEvent.click(screen.getByRole("button", { name: "Take the tour: Preferences" }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Profile" })).toBeTruthy());
  });
});
