import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider } from "../i18n";
import Preferences from "./Preferences";
import { DID_YOU_KNOW_KEY, resetDidYouKnow } from "../play/didYouKnowSetting";

// A loaded machine renders the page slowly (Who am I, then the backends and the preferences): every findBy and waitFor
// of this file waits up to 5 s rather than 1 s, which made it flaky under `make ci`.
configure({ asyncUtilTimeout: 5000 });

const ownerMe = { principal: { id: "owner", roles: ["organiser"] }, account: null, seat: null, keepable_seat: null };
const playerAccount = { id: "acc_00000000000a", username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false };
const playerMe = { principal: { id: `account:${playerAccount.id}`, roles: [] }, account: playerAccount, seat: null, keepable_seat: null };

const playerProfile = {
  account_id: playerAccount.id,
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

const backends = {
  jobs: ["dm", "side", "conversion", "novel", "image.portrait", "image.scene", "image.possession"],
  providers: [
    {
      id: "fake",
      title: "Fake DM (development)",
      jobs: ["dm", "side", "conversion", "novel"],
      models: ["fake-large", "fake-small"],
      efforts: ["auto", "low", "medium", "high", "max"],
      default_model: "fake-large",
    },
    {
      id: "other",
      title: "Other DM",
      jobs: ["dm"],
      models: ["other-1"],
      efforts: ["low", "high"],
      default_model: null,
    },
    {
      id: "fake-images",
      title: "Fake images (development)",
      jobs: ["image.portrait", "image.scene", "image.possession"],
      models: [],
      efforts: [],
      default_model: null,
      development: true,
    },
  ],
};

const preferences = {
  choices: {
    dm: { provider: "fake", model: "fake-large", effort: "auto" },
    side: { provider: "fake", model: "fake-large", effort: "auto" },
    conversion: { provider: "fake", model: "fake-large", effort: "auto" },
    novel: { provider: "fake", model: "fake-large", effort: "auto" },
    "image.portrait": { provider: "fake-images", model: null, effort: null },
    "image.scene": { provider: "fake-images", model: null, effort: null },
    "image.possession": { provider: "fake-images", model: null, effort: null },
  },
  language: "en",
  warnings: [] as string[],
};

type Handler = (init: RequestInit | undefined) => Response;
let routes: Record<string, Handler>;
let fetchMock: ReturnType<typeof vi.fn>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  routes = {
    "GET /api/me": () => json(200, ownerMe),
    "GET /api/backends": () => json(200, backends),
    "GET /api/preferences": () => json(200, preferences),
    "GET /api/connections": () => json(200, { replicate: { state: "unset" }, assetgen: { url: null, token: "unset" } }),
    "GET /api/storage": () =>
      json(200, { backup: null, library: null, schedule: { time: "04:00", last_run: null }, install_id: "ins_000000000001" }),
  };
  fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
    const handler = routes[`${init?.method ?? "GET"} ${path}`];
    return handler ? handler(init) : json(404, { error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** Preferences open on `tab` (`?tab=`), Backends unless asked; "" opens the reader's first tab. */
function renderPreferences(language = "en", tab = "backends") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider language={language}>
        <DialogsProvider>
          <MemoryRouter initialEntries={[tab ? `/preferences?tab=${tab}` : "/preferences"]}>
            <Preferences />
          </MemoryRouter>
        </DialogsProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function row(jobLabel: string): HTMLElement {
  return screen.getByRole("group", { name: jobLabel });
}

/** The backends form's Save; each connection has its own. */
function saveButton(): HTMLElement {
  return within(screen.getByRole("form", { name: "Backends and models" })).getByRole("button", { name: "Save" });
}

function tabLabels(): string[] {
  return screen.getAllByRole("tab").map((tab) => tab.textContent ?? "");
}

function openTab(name: string) {
  fireEvent.click(screen.getByRole("tab", { name }));
}

function optionLabels(select: HTMLElement): string[] {
  return within(select)
    .getAllByRole("option")
    .map((o) => o.textContent ?? "");
}

describe("Preferences", () => {
  it("is headed Preferences", async () => {
    renderPreferences();
    expect(await screen.findByRole("heading", { level: 1, name: "Preferences" })).toBeTruthy();
  });

  it("lists the jobs and filters providers per job", async () => {
    renderPreferences();
    const dm = await screen.findByRole("group", { name: "DM" });
    for (const label of ["Helper tasks", "Module conversion", "Novels", "Portraits", "Scenes", "Possessions"]) {
      expect(row(label)).toBeTruthy();
    }
    expect(optionLabels(within(dm).getByLabelText("Provider"))).toEqual(["Fake DM (development)", "Other DM"]);
    expect(optionLabels(within(row("Helper tasks")).getByLabelText("Provider"))).toEqual(["Fake DM (development)"]);
    expect(optionLabels(within(row("Portraits")).getByLabelText("Provider"))).toEqual([
      "Fake images (development)",
    ]);
    expect(optionLabels(within(dm).getByLabelText("Model"))).toEqual(["Provider default", "fake-large", "fake-small"]);
    expect(optionLabels(within(dm).getByLabelText("Effort"))).toEqual(["Auto", "Low", "Medium", "High", "Max"]);
  });

  it("gives NPC portraits their own row, with No portrait and portraitgen, apart from the PCs' (DEL-248)", async () => {
    routes["GET /api/backends"] = () =>
      json(200, {
        ...backends,
        jobs: [...backends.jobs, "image.npc_portrait"],
        providers: [
          ...backends.providers,
          { id: "portraitgen", title: "portraitgen (free)", jobs: ["image.portrait", "image.npc_portrait"], models: [], efforts: [], default_model: null },
          { id: "none", title: "No portrait", jobs: ["image.npc_portrait"], models: [], efforts: [], default_model: null },
        ],
      });
    renderPreferences();
    const npcs = await screen.findByRole("group", { name: "NPC portraits" });
    // The test's preferences choose nothing for NPCs ("Not offered" first); the server always fills a choice in.
    expect(optionLabels(within(npcs).getByLabelText("Provider")).slice(-2)).toEqual(["portraitgen (free)", "No portrait"]);
    expect(optionLabels(within(row("Portraits")).getByLabelText("Provider"))).not.toContain("No portrait");
  });

  it("changing the provider resets the model to provider default", async () => {
    renderPreferences();
    const dm = await screen.findByRole("group", { name: "DM" });
    const model = within(dm).getByLabelText("Model") as HTMLSelectElement;
    expect(model.value).toBe("fake-large");

    fireEvent.change(within(dm).getByLabelText("Provider"), { target: { value: "other" } });

    expect((within(dm).getByLabelText("Model") as HTMLSelectElement).value).toBe("");
    expect(optionLabels(within(dm).getByLabelText("Model"))).toEqual(["Provider default", "other-1"]);
    expect(optionLabels(within(dm).getByLabelText("Effort"))).toEqual(["Low", "High"]);
  });

  it("a 422 shows its warning text", async () => {
    const warning = "dm: model 'fake-huge' is not offered by 'fake'; using default";
    routes["PUT /api/preferences"] = () => json(422, { error: "Some choices are not valid.", warnings: [warning] });
    renderPreferences();
    await screen.findByRole("group", { name: "DM" });

    fireEvent.click(saveButton());

    expect(await screen.findByText(warning)).toBeTruthy();
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("saves the choices as JSON and says Saved", async () => {
    let sent: unknown;
    routes["PUT /api/preferences"] = (init) => {
      sent = JSON.parse(String(init?.body));
      expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
      return json(200, { ...preferences, ...(sent as object), warnings: [] });
    };
    renderPreferences();
    const dm = await screen.findByRole("group", { name: "DM" });
    fireEvent.change(within(dm).getByLabelText("Model"), { target: { value: "fake-small" } });
    fireEvent.change(within(dm).getByLabelText("Effort"), { target: { value: "high" } });
    fireEvent.change(screen.getByLabelText("Language"), { target: { value: "nl" } });

    fireEvent.click(saveButton());

    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(sent).toEqual({
      choices: { ...preferences.choices, dm: { provider: "fake", model: "fake-small", effort: "high" } },
      language: "nl",
      image_style: { preset: "tone", custom: "" },
    });
  });

  it("chooses the image style: a preset with its sample and words, or custom words (DEL-202)", async () => {
    let sent: { image_style?: unknown } = {};
    routes["GET /api/backends"] = () =>
      json(200, {
        ...backends,
        image_styles: [
          { id: "brom", name: "Gothic and grim (Brom and Easley)", prompt: "In the style of Brom.", sample: false },
          { id: "woodcut", name: "Ink engraving (woodcut)", prompt: "A black-ink woodcut.", sample: true },
        ],
      });
    routes["PUT /api/preferences"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(200, { ...preferences, ...sent, warnings: [] });
    };
    renderPreferences();
    const select = await screen.findByLabelText("Image style");
    expect(optionLabels(select)).toEqual([
      "From the campaign's tone",
      "Gothic and grim (Brom and Easley)",
      "Ink engraving (woodcut)",
      "Custom…",
    ]);
    expect(screen.queryByRole("img", { name: /sample picture/ })).toBeNull();

    fireEvent.change(select, { target: { value: "woodcut" } });
    expect(screen.getByRole("img", { name: "A sample picture in the style Ink engraving (woodcut)" }).getAttribute("src")).toBe(
      "/image-styles/woodcut.webp",
    );
    expect(screen.getByText("A black-ink woodcut.")).toBeTruthy();
    fireEvent.change(select, { target: { value: "brom" } });
    expect(screen.queryByRole("img", { name: /sample picture/ })).toBeNull();

    fireEvent.change(select, { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("Your image style"), { target: { value: "ink and wash" } });
    fireEvent.click(saveButton());
    expect(await screen.findByText("Saved")).toBeTruthy();
    expect(sent.image_style).toEqual({ preset: "custom", custom: "ink and wash" });
  });

  it("shows the server's warnings on load", async () => {
    const warning = "dm: provider 'gone' is not available; using default";
    routes["GET /api/preferences"] = () => json(200, { ...preferences, warnings: [warning] });
    renderPreferences();
    expect(await screen.findByText(warning)).toBeTruthy();
  });

  it("offers every interface language by its own name (DEL-122)", async () => {
    renderPreferences();
    await screen.findByRole("group", { name: "DM" });
    expect(optionLabels(screen.getByLabelText("Language"))).toEqual(["English", "Nederlands", "Français", "Deutsch", "Latviešu"]);
  });

  it("offers the look for this browser only, applied without Save", async () => {
    renderPreferences("en", "browser");
    const look = await screen.findByLabelText("Look");
    expect(optionLabels(look)).toEqual(["Delve today", "Gold and wood", "Dark dungeon"]);
    expect(screen.getByText("For this browser only.")).toBeTruthy();
    fireEvent.change(look, { target: { value: "gold-wood" } });
    expect(document.documentElement.dataset.look).toBe("gold-wood");
    delete document.documentElement.dataset.look;
    localStorage.clear();
  });

  it("turns Did you know off for this browser, without Save", async () => {
    renderPreferences("en", "browser");
    const box = (await screen.findByLabelText('Show "Did you know?" while the DM thinks')) as HTMLInputElement;
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(box.checked).toBe(false);
    expect(localStorage.getItem(DID_YOU_KNOW_KEY)).toBe("off");
    localStorage.clear();
    resetDidYouKnow();
  });

  it("disables model and effort when the provider offers none", async () => {
    renderPreferences();
    const portraits = await screen.findByRole("group", { name: "Portraits" });
    expect((within(portraits).getByLabelText("Model") as HTMLSelectElement).disabled).toBe(true);
    expect((within(portraits).getByLabelText("Effort") as HTMLSelectElement).disabled).toBe(true);
  });

  it("the owner sees every tab but Profile, This browser first, each with its sections", async () => {
    renderPreferences("en", "");
    await screen.findByLabelText("Look");
    // The owner token has no account, so no profile.
    expect(tabLabels()).toEqual(["This browser", "Backends", "Connections", "Storage", "Packs", "Players"]);
    expect(screen.getByRole("tab", { name: "This browser" }).getAttribute("aria-selected")).toBe("true");
    const headings = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings()).toEqual(["This browser"]);
    expect(fetchMock.mock.calls.map(([path]) => path)).not.toContain("/api/backends");

    openTab("Backends");
    await screen.findByRole("group", { name: "DM" });
    expect(headings()).toEqual(["Backends and models"]);
    openTab("Connections");
    await screen.findByRole("group", { name: "Replicate" });
    expect(headings()).toEqual(["Connections"]);
    openTab("Storage");
    await screen.findByRole("group", { name: "Backup store" });
    expect(headings()).toEqual(["Storage", "Owner token"]);
    openTab("Players");
    expect(headings()).toEqual(["Players"]);
    expect(screen.getByRole("link", { name: "Open Players" }).getAttribute("href")).toBe("/preferences/players");
  });

  it("a player sees Profile and This browser only, Profile first", async () => {
    routes["GET /api/me"] = () => json(200, playerMe);
    routes["GET /api/account/sessions"] = () => json(200, []);
    routes["GET /api/account/profile"] = () => json(200, playerProfile);
    renderPreferences("en", "");
    expect(await screen.findByRole("heading", { level: 2, name: "Account" })).toBeTruthy();
    expect(await screen.findByTestId("profile-name")).toBeTruthy();
    expect(tabLabels()).toEqual(["Profile", "This browser"]);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["Profile", "Account"]);
    const profile = document.querySelector("section#profile")!;
    expect(profile.compareDocumentPosition(screen.getByRole("heading", { name: "Account" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    openTab("This browser");
    expect(screen.getByLabelText("Look")).toBeTruthy();
    expect(screen.getByLabelText('Show "Did you know?" while the DM thinks')).toBeTruthy();
    await new Promise((resolve) => setTimeout(resolve, 20));
    // No backends, no Connections, no Players, and nothing of the organiser's asked for.
    expect(screen.queryByRole("group", { name: "DM" })).toBeNull();
    const asked = fetchMock.mock.calls.map(([path]) => path);
    expect(asked).not.toContain("/api/preferences");
    expect(asked).not.toContain("/api/backends");
    expect(asked).not.toContain("/api/connections");
    expect(asked).not.toContain("/api/storage");
  });

  it("a player asking for an organiser's tab gets the first of theirs", async () => {
    routes["GET /api/me"] = () => json(200, playerMe);
    routes["GET /api/account/sessions"] = () => json(200, []);
    routes["GET /api/account/profile"] = () => json(200, playerProfile);
    renderPreferences("en", "backends");
    expect(await screen.findByRole("heading", { level: 2, name: "Account" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Profile" }).getAttribute("aria-selected")).toBe("true");
  });

  it("the owner has no Profile section", async () => {
    renderPreferences();
    await screen.findByRole("group", { name: "DM" });
    expect(screen.queryByRole("tab", { name: "Profile" })).toBeNull();
    expect(fetchMock.mock.calls.map(([path]) => path)).not.toContain("/api/account/profile");
  });

  it("an organiser account has no Connections or Storage tab", async () => {
    routes["GET /api/me"] = () =>
      json(200, { ...playerMe, principal: { ...playerMe.principal, roles: ["organiser"] }, account: { ...playerAccount, organiser: true } });
    routes["GET /api/account/sessions"] = () => json(200, []);
    renderPreferences();
    await screen.findByRole("group", { name: "DM" });
    expect(tabLabels()).toEqual(["Profile", "This browser", "Backends", "Packs", "Players"]);
    expect(fetchMock.mock.calls.map(([path]) => path)).not.toContain("/api/connections");
    expect(fetchMock.mock.calls.map(([path]) => path)).not.toContain("/api/storage");
    openTab("Players");
    expect(screen.getByRole("link", { name: "Open Players" })).toBeTruthy();
  });

  it("shows an organiser seat no Connections and no Storage", async () => {
    routes["GET /api/connections"] = () => json(403, { error: "Only the install's owner can do this." });
    routes["GET /api/storage"] = () => json(403, { error: "Only the install's owner can do this." });
    renderPreferences("en", "connections");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/connections", expect.anything()));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Connections" })).toBeNull());
    expect(screen.queryByRole("group", { name: "Replicate" })).toBeNull();
    openTab("Storage");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/storage", expect.anything()));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Storage" })).toBeNull());
    expect(screen.queryByRole("group", { name: "Backup store" })).toBeNull();
    expect(screen.queryByText("Only the install's owner can do this.")).toBeNull();
  });

  it("lists Replicate among the picture backends once its token is saved, without a restart", async () => {
    let saved = false;
    routes["GET /api/backends"] = () =>
      json(200, saved ? { ...backends, providers: [...backends.providers, replicateProvider] } : backends);
    routes["PUT /api/connections/replicate"] = () => {
      saved = true;
      return json(200, { state: "set" });
    };
    renderPreferences("en", "connections");
    await screen.findByRole("group", { name: "Replicate" });
    fireEvent.change(within(screen.getByRole("group", { name: "Replicate" })).getByLabelText("Token"), {
      target: { value: "tok-SECRET-XYZZY" },
    });
    fireEvent.click(within(screen.getByRole("group", { name: "Replicate" })).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saved).toBe(true));
    openTab("Backends");
    await screen.findByRole("group", { name: "Portraits" });

    await waitFor(() =>
      expect(optionLabels(within(row("Portraits")).getByLabelText("Provider"))).toEqual([
        "Fake images (development)",
        "Replicate",
      ]),
    );
  });

  it("labels each model with its backend and price", async () => {
    routes["GET /api/backends"] = () =>
      json(200, { ...backends, providers: [...backends.providers, replicateProvider, assetgenProvider] });
    routes["GET /api/preferences"] = () =>
      json(200, {
        ...preferences,
        choices: {
          ...preferences.choices,
          "image.portrait": { provider: "replicate", model: null, effort: null },
          "image.scene": { provider: "assetgen", model: null, effort: null },
        },
      });
    renderPreferences();
    const portraits = await screen.findByRole("group", { name: "Portraits" });
    expect(optionLabels(within(portraits).getByLabelText("Model"))).toEqual([
      "Provider default",
      "flux-schnell · replicate · ~$0.003 / image",
      "flux-2-pro · replicate · price unknown",
    ]);
    expect(optionLabels(within(row("Scenes")).getByLabelText("Model"))).toEqual([
      "Provider default",
      "sdxl-turbo · local · free",
      "flux-schnell · replicate · ~$0.003 / image",
    ]);
  });

  it("says a choice can't be used, and still saves it", async () => {
    const problem = "assetgen isn't answering at http://localhost:8765";
    routes["GET /api/backends"] = () =>
      json(200, {
        ...backends,
        providers: [...backends.providers, { ...assetgenProvider, models: [], model_info: {}, problem }],
      });
    const choices = { ...preferences.choices, "image.scene": { provider: "assetgen", model: "sdxl-turbo", effort: null } };
    const warning = `image.scene: can't be used: ${problem}`;
    routes["GET /api/preferences"] = () => json(200, { ...preferences, choices, warnings: [warning] });
    let sent: unknown;
    routes["PUT /api/preferences"] = (init) => {
      sent = JSON.parse(String(init?.body));
      return json(200, { ...preferences, choices, warnings: [warning] });
    };
    renderPreferences();
    const scenes = await screen.findByRole("group", { name: "Scenes" });
    expect(within(scenes).getAllByText(`Can't be used: ${problem}`)).toHaveLength(1);
    // Kept, not fallen back: the notice about defaults doesn't list it.
    expect(screen.queryByText(/so their defaults are used/)).toBeNull();
    expect((within(scenes).getByLabelText("Model") as HTMLSelectElement).value).toBe("sdxl-turbo");

    fireEvent.click(saveButton());

    expect(await screen.findByText("Saved")).toBeTruthy();
    expect((sent as typeof preferences).choices["image.scene"]).toEqual({
      provider: "assetgen",
      model: "sdxl-turbo",
      effort: null,
    });
  });

  it("calls the thorough conversion job Thorough conversion, Grondige conversie in Dutch", async () => {
    routes["GET /api/backends"] = () => json(200, { ...backends, jobs: [...backends.jobs, "conversion.thorough"] });
    const { unmount } = renderPreferences();
    expect(await screen.findByRole("group", { name: "Thorough conversion" })).toBeTruthy();
    unmount();
    renderPreferences("nl");
    expect(await screen.findByRole("group", { name: "Grondige conversie" })).toBeTruthy();
  });

  it("calls the side job Helper tasks, Hulptaken in Dutch", async () => {
    const { unmount } = renderPreferences();
    expect(await screen.findByRole("group", { name: "Helper tasks" })).toBeTruthy();
    unmount();
    renderPreferences("nl");
    expect(await screen.findByRole("group", { name: "Hulptaken" })).toBeTruthy();
  });

  it("warns that a development backend's pictures are fake", async () => {
    routes["GET /api/backends"] = () => json(200, { ...backends, providers: [...backends.providers, assetgenProvider] });
    routes["GET /api/preferences"] = () =>
      json(200, {
        ...preferences,
        choices: { ...preferences.choices, "image.portrait": { provider: "assetgen", model: null, effort: null } },
      });
    renderPreferences();
    const scenes = await screen.findByRole("group", { name: "Scenes" });
    expect(within(scenes).getByText("Fake pictures: for development, not play")).toBeTruthy();
    expect(within(row("Possessions")).getByText("Fake pictures: for development, not play")).toBeTruthy();
    expect(within(row("Portraits")).queryByText(/Fake pictures/)).toBeNull();
    expect(within(row("DM")).queryByText(/Fake pictures/)).toBeNull();

    fireEvent.change(within(scenes).getByLabelText("Provider"), { target: { value: "assetgen" } });
    expect(within(scenes).queryByText(/Fake pictures/)).toBeNull();
  });

  it("names the Claude models plainly, with no bare default", async () => {
    routes["GET /api/backends"] = () => json(200, { ...backends, providers: [claudeProvider, ...backends.providers] });
    routes["GET /api/preferences"] = () =>
      json(200, { ...preferences, choices: { ...preferences.choices, dm: { provider: "claude-cli", model: null, effort: "auto" } } });
    renderPreferences();
    const dm = await screen.findByRole("group", { name: "DM" });
    expect(optionLabels(within(dm).getByLabelText("Model"))).toEqual([
      "Provider default",
      "Opus (most capable)",
      "Sonnet",
      "Haiku (fastest)",
    ]);
  });

  it("says a model gone from its provider can't be used", async () => {
    routes["GET /api/backends"] = () => json(200, { ...backends, providers: [...backends.providers, assetgenProvider] });
    const warning = "image.scene: can't be used: assetgen no longer offers 'old-model'";
    routes["GET /api/preferences"] = () =>
      json(200, {
        ...preferences,
        choices: { ...preferences.choices, "image.scene": { provider: "assetgen", model: "old-model", effort: null } },
        warnings: [warning],
      });
    renderPreferences();
    const scenes = await screen.findByRole("group", { name: "Scenes" });
    expect(within(scenes).getByText("Can't be used: assetgen no longer offers 'old-model'")).toBeTruthy();
    expect((within(scenes).getByLabelText("Model") as HTMLSelectElement).value).toBe("old-model");
  });
});

const imageJobs = ["image.portrait", "image.scene", "image.possession"];

const replicateProvider = {
  id: "replicate",
  title: "Replicate",
  jobs: imageJobs,
  models: ["flux-schnell", "flux-2-pro"],
  efforts: [],
  default_model: "flux-schnell",
  model_info: {
    "flux-schnell": { label: "flux-schnell", backend: "replicate", price: "~$0.003 / image", paid: true },
    "flux-2-pro": { label: "flux-2-pro", backend: "replicate", price: null, paid: true },
  },
  problem: null,
};

const assetgenProvider = {
  id: "assetgen",
  title: "assetgen",
  jobs: imageJobs,
  models: ["sdxl-turbo", "flux-schnell"],
  efforts: [],
  default_model: "sdxl-turbo",
  model_info: {
    "sdxl-turbo": { label: "sdxl-turbo", backend: "local", price: null, paid: false },
    "flux-schnell": { label: "flux-schnell", backend: "replicate", price: "~$0.003 / image", paid: true },
  },
  problem: null,
};

const claudeProvider = {
  id: "claude-cli",
  title: "Claude (claude -p)",
  jobs: ["dm", "side", "conversion", "novel"],
  models: ["opus", "sonnet", "haiku"],
  efforts: ["auto", "low", "medium", "high", "max"],
  default_model: null,
  model_info: {
    opus: { label: "Opus (most capable)", backend: "", price: null, paid: false },
    sonnet: { label: "Sonnet", backend: "", price: null, paid: false },
    haiku: { label: "Haiku (fastest)", backend: "", price: null, paid: false },
  },
  problem: null,
  development: false,
};

describe("Preferences' warnings in the reader's language (T7)", () => {
  const gone = {
    code: "provider_unavailable",
    args: { job: "dm", provider: "gone", outcome: "default" },
    text: "dm: provider 'gone' is not available; using default",
  };

  it("says a stored warning by its code", async () => {
    routes["GET /api/preferences"] = () =>
      json(200, { ...preferences, warnings: [gone.text], coded_warnings: [gone] });
    renderPreferences("nl");
    expect(await screen.findByText("DM: de aanbieder gone is niet beschikbaar; de standaard wordt gebruikt")).toBeTruthy();
    expect(screen.queryByText(gone.text)).toBeNull();
  });

  it("shows a refused choice's warning in its job, by its code", async () => {
    const refused = {
      code: "model_not_offered",
      args: { job: "dm", provider: "fake", model: "fake-huge", outcome: "default" },
      text: "dm: model 'fake-huge' is not offered by 'fake'; using default",
    };
    const language = { code: "language_not_offered", args: { language: "fr" }, text: "language: 'fr' is not offered; using 'en'" };
    routes["PUT /api/preferences"] = () =>
      json(422, {
        error: "Some preferences can't be used.",
        warnings: [refused.text, language.text],
        coded_warnings: [refused, language],
      });
    renderPreferences("nl");
    fireEvent.click(await screen.findByRole("button", { name: "Opslaan" }));
    expect(
      await within(row("DM")).findByText("DM: fake biedt het model fake-huge niet aan; de standaard wordt gebruikt"),
    ).toBeTruthy();
    expect(screen.getByText("De taal fr wordt niet aangeboden, dus Engels wordt gebruikt.")).toBeTruthy();
  });

  it("says a kept choice can't be used, in its job", async () => {
    routes["GET /api/backends"] = () =>
      json(200, { ...backends, providers: [...backends.providers, { ...assetgenProvider, models: [], model_info: {} }] });
    const kept = {
      code: "model_not_offered",
      args: { job: "image.scene", provider: "assetgen", model: "old-model", outcome: "kept" },
      text: "image.scene: can't be used: model 'old-model' is not offered by 'assetgen'",
    };
    routes["GET /api/preferences"] = () =>
      json(200, {
        ...preferences,
        choices: { ...preferences.choices, "image.scene": { provider: "assetgen", model: "old-model", effort: null } },
        warnings: [kept.text],
        coded_warnings: [kept],
      });
    renderPreferences("nl");
    const scenes = await screen.findByRole("group", { name: "Scènes" });
    expect(within(scenes).getByText(/assetgen biedt het model old-model niet aan/)).toBeTruthy();
    expect(screen.queryByText(/standaard wordt gebruikt/)).toBeNull();
  });

  it("falls back to the English text for a code it doesn't know", async () => {
    const odd = { code: "something_new", args: { job: "dm" }, text: "dm: something new; using default" };
    routes["GET /api/preferences"] = () => json(200, { ...preferences, warnings: [odd.text], coded_warnings: [odd] });
    renderPreferences("nl");
    expect(await screen.findByText(odd.text)).toBeTruthy();
  });
});
