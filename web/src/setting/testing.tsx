// Test helpers for the Settings area: the area's routes in a memory router, with the providers they need.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, type RouteObject } from "react-router-dom";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import SettingDetail from "../routes/SettingDetail";
import SettingPage, { NewSettingPage } from "../routes/SettingPage";
import Settings from "../routes/Settings";
import type { CalendarView, SettingInfo, SettingPage as Page } from "./api";

export const areaRoutes: RouteObject[] = [
  { path: "/settings", element: <Settings /> },
  { path: "/settings/:settingId", element: <SettingDetail /> },
  { path: "/settings/:settingId/pages/:title", element: <SettingPage /> },
  { path: "/settings/:settingId/new-page", element: <NewSettingPage /> },
];

/** Renders the area at `path`; `router.state.location` says where a click went. */
export function renderArea(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(areaRoutes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <DialogsProvider>
          <RouterProvider router={router} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return router;
}

/** A calendar of `months` months of 28 days, every fourth one a festival week of 7. */
export function calendarOf(months: number): CalendarView {
  return {
    id: "common",
    era: "CY",
    months: Array.from({ length: months }, (_, i) =>
      i % 4 === 0
        ? { name: `Fest ${i}`, days: 7, season: "Midwinter", weather_season: "winter", festival: true }
        : { name: `Month ${i}`, days: 28, season: "Winter", weather_season: "winter", festival: false },
    ),
    default_start: [576, 99],
  };
}

export function settingInfo(id: string, title: string, extra: Partial<SettingInfo> = {}): SettingInfo {
  return {
    id,
    title,
    kinds: ["settlements", "deities"],
    calendar: calendarOf(16),
    counts: { pages: 0, facts: 0, proposals: 0 },
    maps_in_use: "built-in",
    built_in_maps: [],
    ...extra,
  };
}

export function page(title: string, extra: Partial<Page> = {}): Page {
  return {
    title,
    kind: "settlements",
    fields: {},
    text: "",
    categories: [],
    origin: "shipped",
    dm_only: false,
    campaign_id: null,
    revertible: false,
    redirected_from: null,
    ...extra,
  };
}
