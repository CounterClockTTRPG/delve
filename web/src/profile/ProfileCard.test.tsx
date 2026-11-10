import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import type { ProfileCard as Card } from "./api";
import ProfileCard, { ProfileCards, TableAvatar } from "./ProfileCard";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const ana: Card = {
  account_id: "acc_00000000000a",
  display_name: "Ana",
  pronouns: "she/her",
  avatar: { emblem: "stag" },
  colour: "ember",
  about: "Plays a mean bard.",
};

function renderIn(children: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">{children}</I18nProvider>
    </QueryClientProvider>,
  );
}

describe("ProfileCard", () => {
  it("a player sees name, pronouns, about", async () => {
    stubFetch({ "GET /api/profiles/acc_00000000000a": () => json(200, ana) });
    renderIn(<ProfileCard accountId={ana.account_id} onClose={() => {}} />);
    const card = await screen.findByRole("dialog", { name: "Ana" });
    expect(within(card).getByText("she/her")).toBeTruthy();
    expect(within(card).getByText("Plays a mean bard.")).toBeTruthy();
    expect(within(card).queryByText("Note for the host")).toBeNull();
    expect(within(card).queryByText(/Their time/)).toBeNull();
  });

  it("a host also sees the note and the local time", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-24T19:40:00Z"));
    stubFetch({
      "GET /api/profiles/acc_00000000000a": () =>
        json(200, { ...ana, host_note: "Leaves at ten.", time_zone: "Europe/Brussels" }),
    });
    renderIn(<ProfileCard accountId={ana.account_id} onClose={() => {}} />);
    const card = await screen.findByRole("dialog", { name: "Ana" });
    expect(within(card).getByText("Note for the host")).toBeTruthy();
    expect(within(card).getByText("Leaves at ten.")).toBeTruthy();
    expect(within(card).getByText("Their time: 21:40 (Europe/Brussels)")).toBeTruthy();
  });

  it("says when the player isn't to be read", async () => {
    stubFetch({ "GET /api/profiles/acc_00000000000a": () => json(404, { error: "No such player." }) });
    renderIn(<ProfileCard accountId={ana.account_id} onClose={() => {}} />);
    expect((await screen.findByRole("alert")).textContent).toBe("No such player.");
  });

  it("a click on an avatar at the table opens the card, and Close shuts it", async () => {
    stubFetch({ "GET /api/profiles/acc_00000000000a": () => json(200, ana) });
    renderIn(
      <ProfileCards>
        <TableAvatar profile={ana} />
      </ProfileCards>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ana" }));
    const card = await screen.findByRole("dialog", { name: "Ana" });
    fireEvent.click(within(card).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("outside a table an avatar is no button", () => {
    renderIn(<TableAvatar profile={ana} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
