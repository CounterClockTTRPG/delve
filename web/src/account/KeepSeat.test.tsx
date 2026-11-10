import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, json, sent, stubFetch } from "../play/testing";
import KeepSeat from "./KeepSeat";

afterEach(() => {
  vi.unstubAllGlobals();
});

const account = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };
const me = (keepable: { id: string; name: string } | null) => ({
  principal: { id: `account:${account.id}`, roles: [] },
  account,
  seat: null,
  keepable_seat: keepable,
});

function renderKeep() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <KeepSeat campaignId={CAMPAIGN} />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("KeepSeat", () => {
  it("keeps the old seat", async () => {
    let kept = false;
    const fetchMock = stubFetch({
      [`GET /api/me?campaign=${CAMPAIGN}`]: () => json(200, me(kept ? null : { id: "seat_00000000000a", name: "Ana" })),
      [`POST /api/campaigns/${CAMPAIGN}/seats/keep`]: () => {
        kept = true;
        return json(200, { id: "seat_00000000000a", name: "Ana" });
      },
    });
    renderKeep();
    expect(await screen.findByText("This browser has a seat here from before accounts: Ana.")).toBeTruthy();
    fireEvent.click(screen.getByTestId("keep-seat"));
    await waitFor(() => expect(sent(fetchMock, "POST", `/api/campaigns/${CAMPAIGN}/seats/keep`)).toEqual([{}]));
    await waitFor(() => expect(screen.queryByTestId("keep-seat")).toBeNull());
  });

  it("says nothing without such a seat", async () => {
    const fetchMock = stubFetch({ [`GET /api/me?campaign=${CAMPAIGN}`]: () => json(200, me(null)) });
    renderKeep();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId("keep-seat")).toBeNull();
  });
});
