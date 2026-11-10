// Test helpers for the Rulesets area: its routes in a memory router, with the providers they need.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter, type RouteObject } from "react-router-dom";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import { json } from "../play/testing";
import EntryPage from "./EntryPage";
import RulesetPage from "./RulesetPage";
import Rulesets from "./Rulesets";
import SectionPage from "./SectionPage";

export const areaRoutes: RouteObject[] = [
  { path: "/rulesets", element: <Rulesets /> },
  { path: "/rulesets/:rulesetId", element: <RulesetPage /> },
  { path: "/rulesets/:rulesetId/:section", element: <SectionPage /> },
  { path: "/rulesets/:rulesetId/:section/:entryId", element: <EntryPage /> },
];

/** Renders the area at `path` in `language`; `router.state.location` says where a click went. */
export function renderArea(path: string, language = "en") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(areaRoutes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <DialogsProvider>
          <RouterProvider router={router} />
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
  return router;
}

/** `/api/me` for a player's account, which has no seat in `/api/me` without a campaign. */
export const playerAccount = () =>
  json(200, {
    principal: { id: "account:acc_1", roles: [] },
    account: { id: "acc_1", username: "ash", display_name: "Ash", language: "en", organiser: false, owner: false },
    seat: null,
    keepable_seat: null,
  });

/** `/api/me` for the owner (no seat), or for a player's seat at the Crypt. */
export const owner = () => json(200, { principal: { id: "owner", roles: ["owner", "organiser"] }, seat: null });
export const player = () =>
  json(200, {
    principal: { id: "seat_1", roles: ["player"] },
    seat: {
      id: "seat_1",
      campaign_id: "cmp_00000000000a",
      campaign_name: "The Crypt",
      name: "Ash",
      language: "en",
      role: "player",
      organiser: false,
    },
  });

/** The paths the stubbed fetch was asked, in order. */
export function asked(fetchMock: { mock: { calls: unknown[][] } }): string[] {
  return fetchMock.mock.calls.map(([path]) => String(path));
}

/** `GET /api/rulesets/adnd2e` (with `?campaign=` when given), as a player sees it: no monsters. */
export function rulesetInfo(campaign: string | null = null) {
  const body = {
    id: "adnd2e",
    title: "AD&D 2nd Edition",
    campaign_id: campaign,
    sections: ["spells", "items", "classes", "abilities", "proficiencies", "turning"].map((key) => ({
      key,
      kind: ["abilities", "proficiencies", "turning"].includes(key) ? "table" : "list",
      count: 3,
    })),
  };
  return { [`GET /api/rulesets/adnd2e${campaign ? `?campaign=${campaign}` : ""}`]: () => json(200, body) };
}
