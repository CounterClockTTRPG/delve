import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { GeoDocFeature } from "./editorApi";
import FeatureForm, { reverseFlow } from "./FeatureForm";

const place: GeoDocFeature = {
  type: "Feature",
  id: "hardby",
  geometry: { type: "Point", coordinates: [15, 25] },
  properties: {
    layer: "places",
    kind: "port",
    name: "Hardby",
    description: "",
    dm_notes: "The Despotrix.",
    tags: [],
    hidden: false,
  },
};

const river: GeoDocFeature = {
  type: "Feature",
  id: "selintan",
  geometry: {
    type: "LineString",
    coordinates: [
      [2, 0],
      [3, 15],
      [4, 30],
    ],
  },
  properties: {
    layer: "water",
    kind: "river",
    name: "Selintan",
    description: "",
    dm_notes: "",
    tags: [],
    hidden: false,
    navigable_km: 16.09344,
  },
};

function renderForm(feature: GeoDocFeature, onChange = vi.fn()) {
  render(
    <I18nProvider language="en">
      <FeatureForm feature={feature} units="miles" onChange={onChange} onRemove={() => {}} />
    </I18nProvider>,
  );
  return onChange;
}

const options = (select: HTMLElement) => within(select).getAllByRole("option").map((o) => (o as HTMLOptionElement).value);

describe("FeatureForm", () => {
  it("offers the kinds of its layer", () => {
    renderForm(place);
    expect(options(screen.getByLabelText("Kind"))).toEqual([
      "city",
      "town",
      "village",
      "castle",
      "ruin",
      "dungeon",
      "port",
      "other",
    ]);
  });

  it("offers a road's kinds for a route", () => {
    renderForm({ ...river, properties: { ...river.properties, layer: "routes", kind: "road" } });
    expect(options(screen.getByLabelText("Kind"))).toEqual(["road", "track", "trail"]);
  });

  it("offers a lake or a sea for a water area, and a river only for a line", () => {
    renderForm({
      ...river,
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [0, 0],
            [5, 0],
            [5, 5],
            [0, 0],
          ],
        ],
      },
      properties: { ...river.properties, kind: "lake" },
    });
    expect(options(screen.getByLabelText("Kind"))).toEqual(["lake", "sea"]);
  });

  it("edits a place's hidden flag", () => {
    const onChange = renderForm(place);
    fireEvent.click(screen.getByLabelText("Hidden from the players"));
    expect(onChange).toHaveBeenCalledWith({ ...place, properties: { ...place.properties, hidden: true } });
  });

  it("commits a name once the field is left", () => {
    const onChange = renderForm(place);
    const name = screen.getByLabelText("Name");
    fireEvent.change(name, { target: { value: "Hardby Town" } });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(name);
    expect(onChange).toHaveBeenCalledWith({ ...place, properties: { ...place.properties, name: "Hardby Town" } });
  });

  it("shows a river's navigable stretch in the map's units, and reverses its flow", () => {
    const onChange = renderForm(river);
    expect((screen.getByLabelText("Navigable from its mouth (miles)") as HTMLInputElement).value).toBe("10");
    fireEvent.click(screen.getByRole("button", { name: "Reverse the flow" }));
    const changed = onChange.mock.calls[0][0] as GeoDocFeature;
    expect(changed.geometry).toEqual({
      type: "LineString",
      coordinates: [
        [4, 30],
        [3, 15],
        [2, 0],
      ],
    });
  });

  it("has no flow to reverse but a river's", () => {
    renderForm(place);
    expect(screen.queryByRole("button", { name: "Reverse the flow" })).toBeNull();
    expect(reverseFlow(place)).toBe(place);
  });
});
