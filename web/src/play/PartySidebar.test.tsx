import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { PartyMember } from "./api";
import PartySidebar from "./PartySidebar";
import { base, hostSeat, json, party, renderWith, seat, sent, stubFetch } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PartySidebar", () => {
  it("marching order arrows post the new order", async () => {
    const fetchMock = stubFetch({ [`PUT ${base}/marching-order`]: () => json(200, {}) });
    const onOpenSheet = vi.fn();
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={onOpenSheet} />);

    // HP bars and the front of the line can't move up.
    expect(screen.getByRole("meter", { name: "Birch HP" }).getAttribute("aria-valuenow")).toBe("3");
    expect((screen.getByRole("button", { name: "Move Ash up" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Move Birch up" }));
    await waitFor(() =>
      expect(sent(fetchMock, "PUT", `${base}/marching-order`)).toEqual([
        { order: ["chr_00000000000b", "chr_00000000000a", "chr_00000000000c"] },
      ]),
    );

    fireEvent.click(screen.getByRole("button", { name: "Cedar" }));
    expect(onOpenSheet).toHaveBeenCalledWith("chr_00000000000c");
  });

  it("opens the sheet from anywhere on the card, but not from its arrows", () => {
    stubFetch({ [`PUT ${base}/marching-order`]: () => json(200, {}) });
    const onOpenSheet = vi.fn();
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={onOpenSheet} />);

    fireEvent.click(screen.getByRole("meter", { name: "Birch HP" }));
    expect(onOpenSheet).toHaveBeenCalledOnce();
    expect(onOpenSheet).toHaveBeenCalledWith("chr_00000000000b");
    fireEvent.click(screen.getByRole("button", { name: "Ash" }));
    expect(onOpenSheet).toHaveBeenLastCalledWith("chr_00000000000a");
    expect(onOpenSheet).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Move Birch up" }));
    expect(onOpenSheet).toHaveBeenCalledTimes(2);
  });

  it("shows each character's class and level in shorthand after the HP", () => {
    stubFetch({});
    const classed: PartyMember[] = [
      { ...party[0], cls: "Fighter", levels: { fighter: 1 } },
      { ...party[1], cls: "Mage/Thief", levels: { mage: 3, thief: 4 } },
      { ...party[2], cls: "Sage", levels: { sage: 1 } },
    ];
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={classed} onOpenSheet={() => {}} />);
    const meta = [...document.querySelectorAll(".party-member .row-meta")].map((m) => m.textContent);
    expect(meta).toEqual(["HP 8/10 · AC 5 · F1", "HP 3/9 · AC 5 · MU3/T4", "HP 8/10 · AC 5 · S1"]);
  });

  it("shows each character's portrait, and the initial for one without", () => {
    stubFetch({});
    renderWith(
      <PartySidebar
        campaignId="cmp_00000000000a"
        party={party}
        onOpenSheet={() => {}}
        portraits={{
          chr_00000000000a: { kind: "traits", describe: "a young female elf", seed: "chr_00000000000a" },
          chr_00000000000b: { kind: "image", image_id: "img_00000000000b" },
        }}
      />,
    );
    expect(screen.getByRole("img", { name: "Ash" }).querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("img", { name: "Birch" }).getAttribute("src")).toBe(
      "/api/campaigns/cmp_00000000000a/pictures/img_00000000000b",
    );
    expect(screen.queryByRole("img", { name: "Cedar" })).toBeNull();
    expect(screen.getByRole("button", { name: "Cedar" }).closest("li")?.querySelector(".portrait")?.textContent).toBe("C");
  });

  it("shows a new order at once, while it is saved, and only an organiser's cards move", async () => {
    let answer: (r: Response) => void = () => {};
    stubFetch({ [`PUT ${base}/marching-order`]: () => new Promise<Response>((r) => (answer = r)) as unknown as Response });
    const { unmount } = renderWith(<PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={() => {}} />);
    const names = () => [...document.querySelectorAll(".party-name")].map((b) => b.textContent);
    expect(names()).toEqual(["Ash", "Birch", "Cedar"]);
    expect(document.querySelectorAll(".party-member.movable")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Move Cedar up" }));
    await waitFor(() => expect(names()).toEqual(["Ash", "Cedar", "Birch"]));
    answer(json(200, {}));
    unmount();

    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={() => {}} canReorder={false} />);
    expect(document.querySelectorAll(".party-member.movable")).toHaveLength(0);
  });

  it("shows the party's purse, its coins largest first, those it lacks left out", () => {
    const { unmount } = renderWith(
      <PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={() => {}} coin={{ pp: 0, gp: 1298, ep: 0, sp: 9, cp: 9 }} />,
    );
    expect(screen.getByTestId("party-purse").textContent).toBe("Purse: 1,298 gp · 9 sp · 9 cp");
    unmount();
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={[]} onOpenSheet={() => {}} coin={{ gp: 0 }} />);
    expect(screen.getByTestId("party-purse").textContent).toBe("Purse: empty");
  });

  it("says the purse in Dutch coins", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="nl">
          <PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={() => {}} coin={{ gp: 1298, cp: 3 }} />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("party-purse").textContent).toBe("Beurs: 1.298 gs · 3 ks");
  });

  it("the player's avatar beside the character, the portrait kept", () => {
    stubFetch({});
    const profile = { account_id: "acc_00000000000a", display_name: "Ana", pronouns: "", avatar: { picture: "0123456789ab" }, colour: "jade" };
    renderWith(
      <PartySidebar
        campaignId="cmp_00000000000a"
        party={party}
        onOpenSheet={() => {}}
        portraits={{ chr_00000000000b: { kind: "image", image_id: "img_00000000000b" } }}
        seats={[seat("seat_00000000000a", "Ana", { characters: ["chr_00000000000b"], profile }), hostSeat]}
      />,
    );
    const birch = screen.getByRole("button", { name: "Birch" }).closest("li")!;
    expect(birch.querySelector("img.portrait")?.getAttribute("src"), "the character's portrait stays").toBe(
      "/api/campaigns/cmp_00000000000a/pictures/img_00000000000b",
    );
    const player = birch.querySelector(".party-player")!;
    expect(player.querySelector(".avatar img")?.getAttribute("src")).toBe("/api/profiles/acc_00000000000a/avatar?v=0123456789ab");
    expect(player.textContent).toBe("Ana");
    expect(screen.getByRole("button", { name: "Ash" }).closest("li")!.querySelector(".party-player"), "nobody's").toBeNull();
  });

  it("folds the departed by reason", () => {
    stubFetch({});
    renderWith(
      <PartySidebar
        campaignId="cmp_00000000000a"
        party={party}
        onOpenSheet={() => {}}
        departed={[
          { id: "chr_00000000000d", name: "Tansy", departure: "died" },
          { id: "chr_00000000000e", name: "Rook", departure: "died" },
          { id: "chr_00000000000f", name: "Wren", departure: "left" },
        ]}
      />,
    );
    const away = screen.getByRole("region", { name: "Away from the party" });
    const folds = [...away.querySelectorAll("details")];
    expect(folds.map((f) => f.querySelector("summary")?.textContent)).toEqual(["Fallen: Tansy, Rook", "Left: Wren"]);
    expect(folds.every((f) => !f.open), "folded").toBe(true);
    expect(screen.queryByRole("button", { name: "Move Tansy up" })).toBeNull();
    expect(screen.getAllByRole("listitem").filter((li) => li.classList.contains("party-member"))).toHaveLength(3);
  });

  it("opens a departed PC's sheet", () => {
    stubFetch({});
    const onOpenSheet = vi.fn();
    renderWith(
      <PartySidebar
        campaignId="cmp_00000000000a"
        party={party}
        onOpenSheet={onOpenSheet}
        departed={[{ id: "chr_00000000000d", name: "Tansy", departure: "retired" }]}
      />,
    );
    const fold = screen.getByText("Retired: Tansy").closest("details")!;
    fireEvent.click(screen.getByText("Retired: Tansy"));
    fold.open = true;
    fireEvent.click(within(fold).getByRole("button", { name: "Tansy" }));
    expect(onOpenSheet).toHaveBeenCalledWith("chr_00000000000d");
  });

  it("shows nothing of the departed without any", () => {
    stubFetch({});
    renderWith(<PartySidebar campaignId="cmp_00000000000a" party={party} onOpenSheet={() => {}} departed={[]} />);
    expect(screen.queryByRole("region", { name: "Away from the party" })).toBeNull();
  });

  it("the departed in Dutch", () => {
    stubFetch({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider language="nl">
          <PartySidebar
            campaignId="cmp_00000000000a"
            party={party}
            onOpenSheet={() => {}}
            departed={[{ id: "chr_00000000000d", name: "Tansy", departure: "died" }]}
          />
        </I18nProvider>
      </QueryClientProvider>,
    );
    expect(screen.getByText("Gevallen: Tansy")).toBeTruthy();
  });
});
