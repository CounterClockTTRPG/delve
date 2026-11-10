import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import TimeZonePicker, { byRegion, cityOf, closestZone, useTimeZones } from "./TimeZonePicker";

const ZONES = ["Europe/Riga", "America/Argentina/Buenos_Aires", "Asia/Kolkata", "Europe/Brussels", "UTC", "Africa/Asmara"];

afterEach(() => vi.unstubAllGlobals());

function Picker({ start, none }: { start: string; none?: string }) {
  const zones = useTimeZones(start);
  const [value, setValue] = useState(start);
  return (
    <>
      <TimeZonePicker id="zone" testId="zone" zones={zones} value={value} onChange={setValue} preferred="Europe/Riga" none={none} />
      <output data-testid="value">{value}</output>
    </>
  );
}

function renderPicker(start: string, none?: string) {
  stubFetch({ "GET /api/time-zones": () => json(200, ZONES) });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <Picker start={start} none={none} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("TimeZonePicker", () => {
  it("groups zones by region, other last, and reads the city", () => {
    expect(byRegion(ZONES).map(([region]) => region)).toEqual(["Africa", "America", "Asia", "Europe", "other"]);
    expect(byRegion(ZONES).find(([region]) => region === "Europe")?.[1]).toEqual(["Europe/Brussels", "Europe/Riga"]);
    expect(cityOf("America/Argentina/Buenos_Aires")).toBe("Argentina / Buenos Aires");
    expect(cityOf("UTC")).toBe("UTC");
  });

  it("offers only the server's zones, a region then its cities", async () => {
    renderPicker("Europe/Brussels");
    const region = (await screen.findByRole("option", { name: "Americas" })).closest("select") as HTMLSelectElement;
    expect(Array.from(region.options).map((o) => o.textContent)).toEqual(["Africa", "Americas", "Asia", "Europe", "Other"]);
    const city = screen.getByTestId("zone") as HTMLSelectElement;
    expect(Array.from(city.options).map((o) => o.value)).toEqual(["Europe/Brussels", "Europe/Riga"]);
    fireEvent.change(region, { target: { value: "Africa" } });
    expect(screen.getByTestId("value").textContent).toBe("Africa/Asmara");
    fireEvent.change(region, { target: { value: "Europe" } });
    expect(screen.getByTestId("value").textContent).toBe("Europe/Riga");
  });

  it("empties the value with None and hides the city", async () => {
    renderPicker("", "None");
    const region = (await screen.findByRole("option", { name: "Europe" })).closest("select") as HTMLSelectElement;
    expect(region.value).toBe("");
    expect(screen.queryByTestId("zone")).toBeNull();
    fireEvent.change(region, { target: { value: "Asia" } });
    expect(screen.getByTestId("value").textContent).toBe("Asia/Kolkata");
  });

  it("names the browser's zone as the server does", () => {
    expect(closestZone("Europe/Riga", ZONES)).toBe("Europe/Riga");
    expect(closestZone("Asia/Calcutta", ZONES)).toBe("Asia/Kolkata");
    expect(closestZone("Asia/Calcutta", [])).toBe("Asia/Calcutta");
  });
});
