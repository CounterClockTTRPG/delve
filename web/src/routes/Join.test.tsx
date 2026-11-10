import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { CAMPAIGN, base, character, hostSeat, json, seat, sent, stubFetch } from "../play/testing";
import Join from "./Join";

const TOKEN = "tok-abc";
const PASSWORD = "correct horse battery";
const link = { campaign: { name: "The Crypt", module_title: "The Crypt of Ash" }, languages: ["en", "nl"], you: null };
const account = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "nl", organiser: false, owner: false };
const you = {
  account_id: account.id,
  display_name: "Ana",
  seat_id: null,
  profile: { account_id: account.id, display_name: "Ana", pronouns: "", avatar: { emblem: "eagle" }, colour: "gold" },
};
const bo = seat("seat_00000000000b", "Bo", { characters: ["chr_00000000000b"] });

afterEach(() => {
  vi.unstubAllGlobals();
});

function routes(role: "player" | "observer" = "player") {
  const ana = seat("seat_00000000000a", "Ana", { language: "nl", role });
  return {
    [`GET /api/join/${TOKEN}`]: () => json(200, link),
    [`POST /api/join/${TOKEN}/account`]: () => json(201, { seat: ana, campaign_id: CAMPAIGN, account }),
    [`POST /api/join/${TOKEN}`]: () => json(201, { seat: ana, campaign_id: CAMPAIGN }),
    [`GET ${base}/characters`]: () =>
      json(200, [character("chr_00000000000a", "Ash"), character("chr_00000000000b", "Birch")]),
    [`GET ${base}/seats`]: () => json(200, [hostSeat, bo, ana]),
    [`POST ${base}/characters/chr_00000000000a/claim`]: () => json(200, {}),
    [`POST ${base}/act`]: () => json(202, { beat: { id: "beat_000000000001", status: "running" } }),
  };
}

function renderJoin() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <MemoryRouter initialEntries={[`/join/${TOKEN}`]}>
          <Routes>
            <Route path="/join/:token" element={<Join />} />
            <Route path="/play/:campaignId" element={<p>the play screen</p>} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

async function fillIn(role: "player" | "observer", language = "nl") {
  expect(await screen.findByText("The Crypt")).toBeTruthy();
  fireEvent.change(screen.getByTestId("join-username"), { target: { value: "ana" } });
  fireEvent.change(screen.getByTestId("join-password"), { target: { value: PASSWORD } });
  fireEvent.change(screen.getByTestId("join-name"), { target: { value: " Ana " } });
  fireEvent.change(screen.getByTestId("join-language"), { target: { value: language } });
  fireEvent.click(screen.getByTestId(`join-role-${role}`));
  fireEvent.click(screen.getByTestId("join-submit"));
}

describe("Join", () => {
  it("says who invites, what Delve is, and why Join waits (DEL-264)", async () => {
    stubFetch({ ...routes(), [`GET /api/join/${TOKEN}`]: () => json(200, { ...link, campaign: { ...link.campaign, host: "Raf" } }) });
    renderJoin();
    expect((await screen.findByTestId("join-invited")).textContent).toBe("Raf invited you to their table.");
    expect(screen.getByTestId("join-what").textContent).toContain("the game begins when the host starts the session");
    expect((screen.getByTestId("join-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Fill in every field above to join.")).toBeTruthy();
  });

  it("makes an account and seats it", async () => {
    const fetchMock = stubFetch(routes());
    renderJoin();
    await fillIn("player");
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `/api/join/${TOKEN}/account`)).toEqual([
        { username: "ana", password: PASSWORD, display_name: "Ana", language: "nl", role: "player" },
      ]),
    );
    expect(sent(fetchMock, "POST", `/api/join/${TOKEN}`)).toEqual([]);

    // Birch is Bo's: only Ash is free.
    expect(await screen.findByTestId("join-character-chr_00000000000a")).toBeTruthy();
    expect(screen.queryByTestId("join-character-chr_00000000000b")).toBeNull();
    fireEvent.click(screen.getByTestId("join-character-chr_00000000000a"));
    fireEvent.click(screen.getByTestId("join-play"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/characters/chr_00000000000a/claim`)).toEqual([{}]));
    expect(await screen.findByText("the play screen")).toBeTruthy();
  });

  it("marks the fallen and lets nobody pick them (DEL-190)", async () => {
    const ash = character("chr_00000000000a", "Ash");
    const griff = { ...character("chr_00000000000c", "Griff"), state: { ...ash.state, hp: -10, conditions: ["dead"] } };
    const elmorth = { ...character("chr_00000000000d", "Elmorth"), departure: "died" as const };
    stubFetch({ ...routes(), [`GET ${base}/characters`]: () => json(200, [griff, ash, elmorth]) });
    renderJoin();
    await fillIn("player", "en");
    const first = await screen.findByTestId("join-character-chr_00000000000a");
    const names = [...document.querySelectorAll(".join-character-name")].map((n) => n.textContent);
    expect(names).toEqual(["Ash", "Griff", "Elmorth"]);
    expect((first as HTMLInputElement).disabled).toBe(false);
    for (const id of ["chr_00000000000c", "chr_00000000000d"]) {
      const box = screen.getByTestId(`join-character-${id}`) as HTMLInputElement;
      expect(box.disabled).toBe(true);
      expect(box.closest("li")?.textContent).toContain("fallen");
    }
    expect(screen.queryByText("No character is free right now.")).toBeNull();
  });

  it("speaks the language picked, when Delve has it", async () => {
    stubFetch(routes());
    renderJoin();
    expect(await screen.findByText("The Crypt")).toBeTruthy();
    fireEvent.change(screen.getByTestId("join-language"), { target: { value: "nl" } });
    expect((screen.getByTestId("join-submit") as HTMLButtonElement).textContent).toBe("Aanschuiven");
  });

  it("offers every interface language, each by its own name", async () => {
    stubFetch(routes());
    renderJoin();
    expect(await screen.findByText("The Crypt")).toBeTruthy();
    const options = Array.from((screen.getByTestId("join-language") as HTMLSelectElement).options).map((o) => o.value);
    expect(options).toEqual(["en", "nl", "fr", "de", "lv", "other"]);
    fireEvent.change(screen.getByTestId("join-language"), { target: { value: "de" } });
    expect(screen.getByTestId("join-language").textContent).toContain("Deutsch");
  });

  it("keeps the other language code", async () => {
    const fetchMock = stubFetch(routes("observer"));
    renderJoin();
    expect(await screen.findByText("The Crypt")).toBeTruthy();
    fireEvent.change(screen.getByTestId("join-username"), { target: { value: "ana" } });
    fireEvent.change(screen.getByTestId("join-password"), { target: { value: PASSWORD } });
    fireEvent.change(screen.getByTestId("join-name"), { target: { value: "Ana" } });
    fireEvent.change(screen.getByTestId("join-language"), { target: { value: "other" } });
    fireEvent.change(screen.getByTestId("join-other-language"), { target: { value: "PT" } });
    fireEvent.click(screen.getByTestId("join-role-observer"));
    fireEvent.click(screen.getByTestId("join-submit"));
    await waitFor(() =>
      expect(sent(fetchMock, "POST", `/api/join/${TOKEN}/account`)).toEqual([
        { username: "ana", password: PASSWORD, display_name: "Ana", language: "pt", role: "observer" },
      ]),
    );
    // An observer plays nothing: straight to the table.
    expect(await screen.findByText("the play screen")).toBeTruthy();
  });

  it("asks the DM to make a character, as the first act", async () => {
    const fetchMock = stubFetch(routes());
    renderJoin();
    await fillIn("player");
    fireEvent.change(await screen.findByTestId("join-make-one"), { target: { value: "A halfling thief, please" } });
    fireEvent.click(screen.getByTestId("join-play"));
    await waitFor(() => expect(sent(fetchMock, "POST", `${base}/act`)).toEqual([{ text: "A halfling thief, please" }]));
    expect(await screen.findByText("the play screen")).toBeTruthy();
  });

  it("logs in, then joins", async () => {
    let loggedIn = false;
    const fetchMock = stubFetch({
      ...routes(),
      [`GET /api/join/${TOKEN}`]: () => json(200, loggedIn ? { ...link, you } : link),
      "POST /api/login": () => {
        loggedIn = true;
        return json(200, { account });
      },
    });
    renderJoin();
    expect(await screen.findByText("The Crypt")).toBeTruthy();
    // Make an account is the default; Log in is the other tab.
    expect(screen.getByRole("tab", { name: "Make an account" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(screen.getByRole("tab", { name: "Log in" }));
    fireEvent.change(screen.getByTestId("join-login-username"), { target: { value: "ana" } });
    fireEvent.change(screen.getByTestId("join-login-password"), { target: { value: PASSWORD } });
    fireEvent.click(screen.getByTestId("join-login-submit"));
    // With the link's token: a sign-up that waits for approval is let in by it (DEL-156).
    await waitFor(() =>
      expect(sent(fetchMock, "POST", "/api/login")).toEqual([{ username: "ana", password: PASSWORD, join_token: TOKEN }]),
    );

    // The role step: the display name is the name's placeholder, and an empty name isn't sent.
    const name = (await screen.findByTestId("join-name")) as HTMLInputElement;
    expect(name.placeholder).toBe("Ana");
    expect(screen.queryByTestId("join-username")).toBeNull();
    fireEvent.click(screen.getByTestId("join-submit"));
    await waitFor(() => expect(sent(fetchMock, "POST", `/api/join/${TOKEN}`)).toEqual([{ role: "player" }]));
    expect(await screen.findByTestId("join-character-chr_00000000000a")).toBeTruthy();
  });

  it("an account with a seat goes straight to the table", async () => {
    const fetchMock = stubFetch({
      ...routes(),
      [`GET /api/join/${TOKEN}`]: () => json(200, { ...link, you: { ...you, seat_id: "seat_00000000000a" } }),
      [`POST /api/join/${TOKEN}`]: () => json(200, { seat: seat("seat_00000000000a", "Ana"), campaign_id: CAMPAIGN }),
    });
    renderJoin();
    expect(await screen.findByText("the play screen")).toBeTruthy();
    expect(sent(fetchMock, "POST", `/api/join/${TOKEN}`)).toHaveLength(1);
  });

  it("shows a taken username", async () => {
    stubFetch({ ...routes(), [`POST /api/join/${TOKEN}/account`]: () => json(409, { error: "That username is taken." }) });
    renderJoin();
    await fillIn("player");
    expect((await screen.findByRole("alert")).textContent).toContain("That username is taken.");
    expect(screen.queryByTestId("join-character-chr_00000000000a")).toBeNull();
  });

  it("says when the link doesn't work", async () => {
    stubFetch({
      [`GET /api/join/${TOKEN}`]: () => json(404, { error: "This join link doesn't work: ask the host for a new one." }),
    });
    renderJoin();
    expect(await screen.findByText(/This join link doesn't work/)).toBeTruthy();
  });

  it("ties each character's box to its label, so the name checks it (G3, T-a)", async () => {
    stubFetch(routes());
    renderJoin();
    await fillIn("player");
    const box = (await screen.findByLabelText(/Ash/)) as HTMLInputElement;
    expect(box).toBe(screen.getByTestId("join-character-chr_00000000000a"));
    const label = document.querySelector(`label[for="${box.id}"]`);
    expect(label?.textContent).toContain("Ash");
    expect(label?.contains(box)).toBe(false);
    fireEvent.click(label!);
    expect(box.checked).toBe(true);
  });

  it("names a character's race and class in the language picked (T7)", async () => {
    stubFetch(routes());
    renderJoin();
    await fillIn("player");
    const box = (await screen.findByLabelText(/Ash/)) as HTMLInputElement;
    expect(document.querySelector(`label[for="${box.id}"]`)?.textContent).toContain("Mens Krijger");
  });

  it("says who you are", async () => {
    let loggedIn = true;
    const fetchMock = stubFetch({
      ...routes(),
      [`GET /api/join/${TOKEN}`]: () => json(200, loggedIn ? { ...link, you } : link),
      "POST /api/logout": () => {
        loggedIn = false;
        return json(200, {});
      },
    });
    const { container } = renderJoin();
    expect(await screen.findByText("You are Ana")).toBeTruthy();
    await waitFor(() => expect(container.querySelector(".join-you .avatar[data-emblem='eagle']")).not.toBeNull());
    expect(
      fetchMock.mock.calls.some(([p]) => p === "/api/account/profile"),
      "the join link's `you` carries the profile",
    ).toBe(false);
    fireEvent.click(screen.getByTestId("join-not-you"));
    expect(screen.getByTestId("join-not-you").textContent).toBe("Not you? Log out");
    await waitFor(() => expect(fetchMock.mock.calls.some(([p, init]) => p === "/api/logout" && init?.method === "POST")).toBe(true));
    expect(await screen.findByRole("tab", { name: "Make an account" })).toBeTruthy();
    expect(screen.queryByText("You are Ana")).toBeNull();
  });
});

describe("Join: the table's listing (DEL-204)", () => {
  it("shows the description and the places, and offers only watching at a full table", async () => {
    const full = {
      ...link,
      campaign: {
        ...link.campaign,
        description: "Newcomers **welcome**.",
        slots: 2,
        taken: 2,
        full: true,
        house_rules: [{ id: "hr_1", title: "Critical hits double damage", body_md: "" }],
      },
    };
    stubFetch({ ...routes(), [`GET /api/join/${TOKEN}`]: () => json(200, full) });
    renderJoin();
    expect((await screen.findByTestId("join-full")).textContent).toContain("You can still join to watch");
    expect(screen.getByTestId("table-about").textContent).toContain("Critical hits double damage");
    expect(screen.getByTestId("table-places").textContent).toBe("The table is full: 2 of 2 places taken");
    const play = screen.getByTestId("join-role-player") as HTMLInputElement;
    expect(play.disabled).toBe(true);
    await waitFor(() => expect((screen.getByTestId("join-role-observer") as HTMLInputElement).checked).toBe(true));
  });

  it("asks the host to watch where they let watchers in, and offers no watching where the table takes none (DEL-215)", async () => {
    const approved = { ...link, campaign: { ...link.campaign, observers: "approved" } };
    const request = { id: "jrq_00000000000a", campaign_id: CAMPAIGN, status: "pending", role: "observer", messages: [] };
    const fetchMock = stubFetch({
      ...routes("observer"),
      [`GET /api/join/${TOKEN}`]: () => json(200, approved),
      [`POST /api/join/${TOKEN}/account`]: () => json(202, { join_request: request, campaign_id: CAMPAIGN, account }),
    });
    const { unmount } = renderJoin();
    expect((await screen.findByTestId("join-role-observer")).closest("label")?.textContent).toContain("the host lets you in");
    fireEvent.change(screen.getByTestId("join-username"), { target: { value: "ana" } });
    fireEvent.change(screen.getByTestId("join-password"), { target: { value: PASSWORD } });
    fireEvent.change(screen.getByTestId("join-name"), { target: { value: "Ana" } });
    fireEvent.click(screen.getByTestId("join-role-observer"));
    fireEvent.click(screen.getByTestId("join-submit"));
    expect((await screen.findByTestId("join-asked-to-watch")).textContent).toContain("Your request to watch went to the host");
    expect(sent(fetchMock, "POST", `/api/join/${TOKEN}/account`)[0]).toMatchObject({ role: "observer" });
    expect(screen.queryByText("the play screen")).toBeNull();
    unmount();

    stubFetch({ ...routes(), [`GET /api/join/${TOKEN}`]: () => json(200, { ...link, campaign: { ...link.campaign, observers: "nobody" } }) });
    renderJoin();
    expect(((await screen.findByTestId("join-role-observer")) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("This table takes no observers.")).toBeTruthy();
  });
});
