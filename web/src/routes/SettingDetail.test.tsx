import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { json, stubFetch, type Handler } from "../play/testing";
import { renderArea, settingInfo } from "../setting/testing";

const base = "/api/settings/greyhawk";
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof stubFetch>;

beforeEach(() => {
  routes = { [`GET ${base}`]: () => json(200, settingInfo("greyhawk", "Greyhawk")) };
  fetchMock = stubFetch(routes);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("SettingDetail", () => {
  it("shows the setting's title and the Lore tab first", async () => {
    renderArea("/settings/greyhawk");
    expect(await screen.findByRole("heading", { level: 1, name: "Greyhawk" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Lore" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("link", { name: "Write a page" }).getAttribute("href")).toBe("/settings/greyhawk/new-page");
  });

  it("searches after a pause and marks the words found", async () => {
    routes[`GET ${base}/search?q=hardby&limit=10`] = () =>
      json(200, {
        query: "hardby",
        results: [
          { kind: "settlements", key: "Hardby", title: "Hardby", text: "…the town of <<Hardby>> on the bay…", origin: "shipped" },
          { kind: "settlements", key: "Hardby Mill", title: "Hardby Mill", text: "<<Hardby>> mill", origin: "addition" },
        ],
      });
    renderArea("/settings/greyhawk");
    const box = await screen.findByRole("searchbox", { name: "Search the lore" });
    vi.useFakeTimers();
    fireEvent.change(box, { target: { value: "hardby" } });
    await act(async () => {
      vi.advanceTimersByTime(299);
    });
    expect(fetchMock.mock.calls.some(([p]) => String(p).includes("/search"))).toBe(false);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    vi.useRealTimers();
    const link = await screen.findByRole("link", { name: "Hardby" });
    expect(link.getAttribute("href")).toBe("/settings/greyhawk/pages/Hardby");
    const hit = link.closest("li")!;
    expect(hit.querySelector("mark")?.textContent).toBe("Hardby");
    expect(hit.textContent).toContain("…the town of Hardby on the bay…");
    const added = screen.getByRole("link", { name: "Hardby Mill" }).closest("li")!;
    expect(within(added).getByText("Added on this install")).toBeTruthy();
  });

  it("says when a search finds nothing", async () => {
    routes[`GET ${base}/search?q=zzz&limit=10`] = () => json(200, { query: "zzz", results: [] });
    renderArea("/settings/greyhawk");
    fireEvent.change(await screen.findByRole("searchbox", { name: "Search the lore" }), { target: { value: "zzz" } });
    expect(await screen.findByText("Nothing found.")).toBeTruthy();
  });

  it("a kind chip lists that kind's pages, and its filter narrows them", async () => {
    routes[`GET ${base}/kinds/deities`] = () =>
      json(200, {
        kind: "deities",
        results: [
          { kind: "deities", key: "Boccob", title: "Boccob", text: "", origin: "shipped" },
          { kind: "deities", key: "Pelor", title: "Pelor", text: "", origin: "override" },
        ],
      });
    routes[`GET ${base}/kinds/deities?q=pel`] = () =>
      json(200, { kind: "deities", results: [{ kind: "deities", key: "Pelor", title: "Pelor", text: "", origin: "override" }] });
    renderArea("/settings/greyhawk");
    fireEvent.click(await screen.findByRole("button", { name: "deities" }));
    expect((await screen.findByRole("link", { name: "Boccob" })).getAttribute("href")).toBe("/settings/greyhawk/pages/Boccob");
    expect(within(screen.getByRole("link", { name: "Pelor" }).closest("li")!).getByText("Changed on this install")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter" }), { target: { value: "pel" } });
    await waitFor(() => expect(screen.queryByRole("link", { name: "Boccob" })).toBeNull());
    expect(screen.getByRole("link", { name: "Pelor" })).toBeTruthy();
  });

  it("the calendar tab lists every month in order, the festivals marked, and the era", async () => {
    const router = renderArea("/settings/greyhawk");
    fireEvent.click(await screen.findByRole("tab", { name: "Calendar" }));
    expect(router.state.location.search).toBe("?tab=calendar");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(16);
    expect(within(rows[0]).getByText("Fest 0")).toBeTruthy();
    expect(within(rows[0]).getByText("Festival")).toBeTruthy();
    expect(within(rows[1]).getByText("Month 1")).toBeTruthy();
    expect(within(rows[1]).queryByText("Festival")).toBeNull();
    expect(within(rows[1]).getByText("28")).toBeTruthy();
    expect(screen.getByText("Era: CY")).toBeTruthy();
  });

  it("an unknown setting says so", async () => {
    routes[`GET ${base}`] = () => json(404, { error: "There is no setting 'greyhawk'." });
    renderArea("/settings/greyhawk");
    expect(await screen.findByText("The setting couldn't be read: There is no setting 'greyhawk'.")).toBeTruthy();
  });
});
