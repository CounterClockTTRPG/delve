import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import KnownPlaces from "./KnownPlaces";
import { seatView } from "./testing";

describe("KnownPlaces", () => {
  it("lists only the places the view holds, with You are here at the party's", () => {
    const onSelect = vi.fn();
    render(
      <I18nProvider language="en">
        <KnownPlaces view={seatView()} onSelect={onSelect} />
      </I18nProvider>,
    );
    const list = screen.getByRole("list", { name: "Known places" });
    const items = list.querySelectorAll("li");
    expect([...items].map((li) => li.querySelector(".known-place-name")?.textContent)).toEqual(["Greyhawk", "Hardby"]);
    // The road and the river are features, not places.
    expect(screen.queryByText("The old road")).toBeNull();
    expect(screen.queryByText("Selintan")).toBeNull();
    expect(items[0].textContent).toContain("You are here");
    expect(items[1].textContent).not.toContain("You are here");
    expect(items[0].textContent).toContain("The Gem of the Flanaess.");
    fireEvent.click(screen.getByRole("button", { name: /Hardby/ }));
    expect(onSelect).toHaveBeenCalledWith("hardby");
  });

  it("says so when no place is known yet", () => {
    render(
      <I18nProvider language="en">
        <KnownPlaces view={seatView({ features: [], party: null })} />
      </I18nProvider>,
    );
    expect(screen.getByText("No places known yet.")).toBeTruthy();
  });
});
