import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { json, stubFetch } from "../play/testing";
import type { ProfileCard } from "./api";
import ProfileSection from "./ProfileSection";

configure({ asyncUtilTimeout: 5000 });

afterEach(() => vi.unstubAllGlobals());

const own: ProfileCard = {
  account_id: "acc_00000000000a",
  display_name: "Ana",
  pronouns: "",
  avatar: { emblem: "stag" },
  avatar_emblem: "stag",
  colour: "teal",
  about: "",
  host_note: "",
  time_zone: null,
  language: "en",
};

const ZONES = ["Africa/Asmara", "Europe/Brussels", "Europe/Riga", "UTC"];

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language="en">
        <ProfileSection />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

/** The calls made to `path` with `method`, with their init. */
function calls(fetchMock: ReturnType<typeof vi.fn>, method: string, path: string): RequestInit[] {
  return fetchMock.mock.calls.filter(([p, init]) => p === path && (init?.method ?? "GET") === method).map(([, init]) => init);
}

function pick(file: File) {
  fireEvent.change(screen.getByTestId("profile-upload"), { target: { files: [file] } });
}

describe("ProfileSection", () => {
  it("saves the fields", async () => {
    const fetchMock = stubFetch({
      "GET /api/time-zones": () => json(200, ZONES),
      "GET /api/account/profile": () => json(200, own),
      "PUT /api/account/profile": (init) => json(200, { ...own, ...JSON.parse(String(init!.body)) }),
    });
    renderSection();
    const name = (await screen.findByTestId("profile-name")) as HTMLInputElement;
    expect(name.value).toBe("Ana");
    fireEvent.change(name, { target: { value: "Ana the Bold" } });
    fireEvent.change(screen.getByTestId("profile-pronouns"), { target: { value: "she/her" } });
    fireEvent.click(screen.getByTestId("profile-emblem-oak"));
    fireEvent.click(screen.getByTestId("profile-colour-ember"));
    fireEvent.change(screen.getByTestId("profile-about"), { target: { value: "Plays a mean bard." } });
    expect(screen.getByText("18 / 500")).toBeTruthy();
    fireEvent.change(screen.getByTestId("profile-note"), { target: { value: "Leaves at ten." } });
    expect(screen.getByText("Only the hosts of your tables read this.")).toBeTruthy();
    fireEvent.change(await screen.findByTestId("profile-time-zone-region"), { target: { value: "Europe" } });
    fireEvent.change(screen.getByTestId("profile-time-zone"), { target: { value: "Europe/Brussels" } });
    fireEvent.click(screen.getByTestId("profile-save"));
    await screen.findByText("Saved.");
    const [put] = calls(fetchMock, "PUT", "/api/account/profile");
    expect(JSON.parse(String(put.body))).toEqual({
      display_name: "Ana the Bold",
      pronouns: "she/her",
      avatar_emblem: "oak",
      colour: "ember",
      language: "en",
      about: "Plays a mean bard.",
      host_note: "Leaves at ten.",
      time_zone: "Europe/Brussels",
    });
  });

  it("shows a language Delve speaks as itself, not as another code", async () => {
    stubFetch({ "GET /api/account/profile": () => json(200, { ...own, language: "fr" }) });
    renderSection();
    const language = (await screen.findByTestId("profile-language")) as HTMLSelectElement;
    expect(language.value).toBe("fr");
    expect(Array.from(language.options).map((o) => o.value)).toEqual(["en", "nl", "fr", "de", "lv", "other"]);
  });

  it("offers None as a time zone, and sends it as null", async () => {
    const fetchMock = stubFetch({
      "GET /api/time-zones": () => json(200, ZONES),
      "GET /api/account/profile": () => json(200, { ...own, time_zone: "Europe/Brussels" }),
      "PUT /api/account/profile": (init) => json(200, { ...own, ...JSON.parse(String(init!.body)) }),
    });
    renderSection();
    const region = (await screen.findByTestId("profile-time-zone-region")) as HTMLSelectElement;
    expect(region.value).toBe("Europe");
    expect((screen.getByTestId("profile-time-zone") as HTMLSelectElement).value).toBe("Europe/Brussels");
    expect(region.options[0].textContent).toBe("None");
    fireEvent.change(region, { target: { value: "" } });
    expect(screen.queryByTestId("profile-time-zone")).toBeNull();
    fireEvent.click(screen.getByTestId("profile-save"));
    await screen.findByText("Saved.");
    expect(JSON.parse(String(calls(fetchMock, "PUT", "/api/account/profile")[0].body)).time_zone).toBeNull();
  });

  it("uploads a picture and shows it", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/profile": () => json(200, own),
      "POST /api/account/avatar": () => json(200, { ...own, avatar: { picture: "0123456789ab" } }),
    });
    const { container } = renderSection();
    await screen.findByTestId("profile-upload");
    expect((screen.getByTestId("profile-upload") as HTMLInputElement).accept).toBe("image/png,image/jpeg,image/webp");
    const file = new File([new Uint8Array(1000)], "me.png", { type: "image/png" });
    pick(file);
    await waitFor(() => expect(container.querySelector(".profile-preview img")).not.toBeNull());
    expect(container.querySelector(".profile-preview img")!.getAttribute("src")).toBe(
      "/api/profiles/acc_00000000000a/avatar?v=0123456789ab",
    );
    const [post] = calls(fetchMock, "POST", "/api/account/avatar");
    expect(new Headers(post.headers).get("Content-Type")).toBe("image/png");
    expect(post.body).toBe(file);
    expect(screen.getByRole("button", { name: "Remove the picture" })).toBeTruthy();
  });

  it("refuses a picture over 2 MB without sending it", async () => {
    const fetchMock = stubFetch({ "GET /api/account/profile": () => json(200, own) });
    renderSection();
    await screen.findByTestId("profile-upload");
    pick(new File([new Uint8Array(2 * 1024 * 1024 + 1)], "big.jpg", { type: "image/jpeg" }));
    expect((await screen.findByRole("alert")).textContent).toBe("At most 2 MB.");
    expect(calls(fetchMock, "POST", "/api/account/avatar")).toHaveLength(0);
  });

  it("choosing an emblem removes the picture", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/profile": () => json(200, { ...own, avatar: { picture: "0123456789ab" } }),
      "PUT /api/account/profile": (init) => {
        const body = JSON.parse(String(init!.body));
        return json(200, { ...own, ...body, avatar: { emblem: body.avatar_emblem } });
      },
      "DELETE /api/account/avatar": () => json(200, own),
    });
    const { container } = renderSection();
    await screen.findByRole("button", { name: "Remove the picture" });
    fireEvent.click(screen.getByTestId("profile-emblem-wolf"));
    expect(container.querySelector(".profile-preview img"), "the preview shows the emblem at once").toBeNull();
    fireEvent.click(screen.getByTestId("profile-save"));
    await screen.findByText("Saved.");
    expect(JSON.parse(String(calls(fetchMock, "PUT", "/api/account/profile")[0].body)).avatar_emblem).toBe("wolf");
    expect(screen.queryByRole("button", { name: "Remove the picture" })).toBeNull();
  });

  it("removes the picture", async () => {
    const fetchMock = stubFetch({
      "GET /api/account/profile": () => json(200, { ...own, avatar: { picture: "0123456789ab" } }),
      "DELETE /api/account/avatar": () => json(200, own),
    });
    const { container } = renderSection();
    fireEvent.click(await screen.findByRole("button", { name: "Remove the picture" }));
    await waitFor(() => expect(container.querySelector(".profile-preview img")).toBeNull());
    expect(calls(fetchMock, "DELETE", "/api/account/avatar")).toHaveLength(1);
  });

  it("shows the server's refusal", async () => {
    stubFetch({
      "GET /api/account/profile": () => json(200, own),
      "PUT /api/account/profile": () => json(422, { error: "A display name has 1 to 40 characters." }),
    });
    renderSection();
    fireEvent.click(await screen.findByTestId("profile-save"));
    expect((await screen.findByRole("alert")).textContent).toBe("A display name has 1 to 40 characters.");
  });
});
