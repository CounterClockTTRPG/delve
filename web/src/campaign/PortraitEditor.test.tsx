import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { generate, render } from "portraitgen";
import { portraitSvg } from "../components/Portrait";
import { base, character, json, renderWith, sent, stubFetch } from "../play/testing";
import CharacterSheet from "./CharacterSheet";
import { decodeTraits, EDITOR_URL, encodeTraits, startingTraits } from "./PortraitEditor";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const ash = { ...character("chr_00000000000a", "Ash"), portrait_editable: true };
const editPath = `${base}/characters/chr_00000000000a/portrait`;
const edited = { ...generate({ describe: "a stout old male dwarf", seed: "abc" }), hair: "receding" };

/** The editor's frame keeps the portrait it shows in its address; jsdom loads no page, so this stands in for it. */
function frameShows(hash: string) {
  vi.spyOn(HTMLIFrameElement.prototype, "contentWindow", "get").mockReturnValue({ location: { hash } } as Window);
}

describe("Edit portrait (DEL-238)", () => {
  it("is on the sheet in place of Repaint while portraitgen draws PCs", () => {
    stubFetch({});
    renderWith(<CharacterSheet character={ash} mayRepaint />);
    expect(screen.getByRole("button", { name: "Edit Ash's portrait" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Repaint Ash's portrait" })).toBeNull();
  });

  it("isn't there for a reader who may not change the portrait, nor while one is painted", () => {
    stubFetch({});
    const { unmount } = renderWith(<CharacterSheet character={ash} />);
    expect(screen.queryByRole("button", { name: "Edit Ash's portrait" })).toBeNull();
    unmount();
    renderWith(<CharacterSheet character={{ ...ash, portrait_painting: { provider: "x", queue: null } }} mayRepaint />);
    expect(screen.queryByRole("button", { name: "Edit Ash's portrait" })).toBeNull();
  });

  it("opens portraitgen's editor on the portrait the sheet shows, and saves what it shows on Save", async () => {
    const fetchMock = stubFetch({ [`PUT ${editPath}`]: () => json(200, { portrait: { kind: "traits" } }) });
    const portrait = { kind: "traits" as const, describe: "a scarred old dwarf", seed: "chr_00000000000a" };
    renderWith(<CharacterSheet character={{ ...ash, sheet: { ...ash.sheet, portrait } }} mayRepaint />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Ash's portrait" }));
    const frame = (await screen.findByTitle("Ash's portrait")) as HTMLIFrameElement;
    const [url, hash] = frame.getAttribute("src")!.split("#");
    expect(url).toBe(EDITOR_URL);
    expect(decodeTraits(hash)).toEqual(generate({ describe: "a scarred old dwarf", seed: "chr_00000000000a" }));

    frameShows(`#${encodeTraits(edited)}`);
    fireEvent.load(frame);
    fireEvent.click(screen.getByRole("button", { name: "Save portrait" }));
    await waitFor(() => expect(sent(fetchMock, "PUT", editPath)).toEqual([{ traits: edited }]));
    await waitFor(() => expect(screen.queryByTitle("Ash's portrait")).toBeNull());
  });

  it("says the server's reason when the save is refused, and keeps the editor open", async () => {
    stubFetch({ [`PUT ${editPath}`]: () => json(422, { error: "These aren't portraitgen's traits: hair: one of portraitgen's ids." }) });
    renderWith(<CharacterSheet character={ash} mayRepaint />);
    fireEvent.click(screen.getByRole("button", { name: "Edit Ash's portrait" }));
    const frame = await screen.findByTitle("Ash's portrait");
    frameShows(`#${encodeTraits(edited)}`);
    fireEvent.load(frame);
    fireEvent.click(screen.getByRole("button", { name: "Save portrait" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "These aren't portraitgen's traits: hair: one of portraitgen's ids.",
    );
    expect(screen.getByTitle("Ash's portrait")).toBeTruthy();
  });
});

describe("an edited portrait's traits", () => {
  it("travel in the editor's link, whatever their letters", () => {
    const traits = { ...edited, seed: "Éowyn-ø" };
    expect(decodeTraits(`#${encodeTraits(traits)}`)).toEqual(traits);
    expect(decodeTraits("#not base64!")).toBeNull();
    expect(decodeTraits(`#${btoa("[1, 2]")}`)).toBeNull();
  });

  it("open as they were saved, and a painted portrait opens on the sheet's race and class", () => {
    const saved = { ...ash, sheet: { ...ash.sheet, portrait: { kind: "traits" as const, describe: "x", seed: "y", traits: edited } } };
    expect(startingTraits(saved, "illustrated")).toBe(edited);
    const painted = { ...ash, sheet: { ...ash.sheet, portrait: { kind: "image" as const, image_id: "img_1" } } };
    const opened = startingTraits(painted, "realistic");
    expect(opened).toEqual({ ...generate({ describe: "a human fighter", seed: "chr_00000000000a" }), style: "realistic" });
  });

  it("are what the portrait draws, over its description and seed", () => {
    const portrait = { kind: "traits" as const, describe: "a tall elf", seed: "s1", traits: edited };
    expect(portraitSvg(portrait, 64, "t")).toBe(render(edited, { size: 64, idPrefix: "t" }));
    const broken = { ...portrait, traits: { nonsense: true } };
    expect(portraitSvg(broken, 64, "t")).toBe(render(generate({ describe: "a tall elf", seed: "s1" }), { size: 64, idPrefix: "t" }));
  });
});
