import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { I18nProvider, LANGUAGES } from "../i18n";
import { HelpIndex, HelpTopicPage } from "./HelpPages";
import { HelpPanel } from "./HelpPanel";
import {
  AUDIENCES,
  TOPICS,
  inLanguage,
  loadTopics,
  parseTopic,
  parseTranslation,
  topic,
  topicHtml,
  topicsFor,
  type Topic,
} from "./topics";

const made = (over: Partial<Topic>): Topic => ({
  slug: "x",
  title: "X",
  audience: "player",
  summary: "",
  screens: [],
  order: 1,
  related: [],
  body: "",
  ...over,
});

describe("help topics", () => {
  it("reads a topic's header and keeps its Markdown", () => {
    const parsed = parseTopic(
      "hosting",
      "---\ntitle: Hosting\naudience: organiser\nsummary: Run a table.\nscreens: /campaigns, /campaigns/:id\norder: 2\nrelated: a, b\n---\nSome **text**.\n",
    );
    expect(parsed).toEqual({
      slug: "hosting",
      title: "Hosting",
      audience: "organiser",
      summary: "Run a table.",
      screens: ["/campaigns", "/campaigns/:id"],
      order: 2,
      related: ["a", "b"],
      body: "Some **text**.",
    });
  });

  it("refuses a topic without a header, a title or a known audience", () => {
    expect(() => parseTopic("a", "No header")).toThrow(/header/);
    expect(() => parseTopic("b", "---\naudience: player\n---\n")).toThrow(/title/);
    expect(() => parseTopic("c", "---\ntitle: C\naudience: dragon\n---\n")).toThrow(/audience/);
  });

  it("shows a reader the topics about their screen, for their audience and those below it, their own first", () => {
    const topics = [
      made({
        slug: "newcomer",
        audience: "newcomer",
        screens: ["/campaigns/:id"],
      }),
      made({ slug: "player", audience: "player", screens: ["/campaigns/:id"] }),
      made({
        slug: "organiser",
        audience: "organiser",
        screens: ["/campaigns/:id"],
      }),
      made({ slug: "owner", audience: "owner", screens: ["/campaigns/:id"] }),
      made({ slug: "elsewhere", audience: "player", screens: ["/tables"] }),
    ];
    const slugs = (role: Topic["audience"]) => topicsFor("/campaigns/cmp_1", role, topics).map((t) => t.slug);
    expect(slugs("player")).toEqual(["player", "newcomer"]);
    expect(slugs("organiser")).toEqual(["organiser", "newcomer", "player"]);
    expect(slugs("owner")).toEqual(["owner", "newcomer", "player", "organiser"]);
    expect(topicsFor("/campaigns", "owner", topics)).toEqual([]);
  });

  it("ships topics whose links to each other all lead somewhere", () => {
    const slugs = new Set(TOPICS.map((t) => t.slug));
    expect(TOPICS.length).toBeGreaterThan(0);
    for (const t of TOPICS) {
      expect(AUDIENCES).toContain(t.audience);
      for (const next of t.related) expect(slugs, `${t.slug} leads on to ${next}`).toContain(next);
    }
  });

  it("renders Markdown with the topic's own HTML kept", () => {
    const html = topicHtml('Read **this**.\n\n<p class="note">A note.</p>');
    expect(html).toContain("<strong>this</strong>");
    expect(html).toContain('<p class="note">A note.</p>');
  });
});

function at(path: string, ui: React.ReactNode, route = "*") {
  return render(
    <I18nProvider language="en">
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={ui} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("help pages", () => {
  it("lists every topic by audience, each linking to its page", () => {
    at("/help", <HelpIndex />);
    expect(screen.getByRole("heading", { level: 1, name: "Help" })).toBeTruthy();
    const playing = screen.getByRole("region", { name: "Playing" });
    expect(within(playing).getByRole("link", { name: "Getting in" }).getAttribute("href")).toBe("/help/getting-in");
    const sections = screen.getAllByRole("region").map((section) => section.getAttribute("aria-labelledby"));
    expect(sections[0]).toBe("help-newcomer");
    const newcomer = screen.getByRole("region", { name: "New to roleplaying" });
    expect(within(newcomer).getByRole("link", { name: "What a roleplaying game is" }).getAttribute("href")).toBe(
      "/help/what-is-a-roleplaying-game",
    );
    const owner = screen.getByRole("region", { name: "Running Delve" });
    expect(
      within(owner).getByRole("link", {
        name: "Connecting Delve to other services",
      }),
    ).toBeTruthy();
  });

  it("shows a topic with what to read next", () => {
    at("/help/getting-in", <HelpTopicPage />, "/help/:slug");
    expect(screen.getByRole("heading", { level: 1, name: "Getting in" })).toBeTruthy();
    const next = screen.getByRole("navigation", { name: "Read next" });
    expect(within(next).getByRole("link", { name: "Finding a table" }).getAttribute("href")).toBe("/help/find-a-table");
  });

  it("says when there is no such topic", () => {
    at("/help/dragons", <HelpTopicPage />, "/help/:slug");
    expect(screen.getByRole("heading", { name: "No such topic" })).toBeTruthy();
  });
});

describe("the help panel", () => {
  it("opens from the nav on this screen's topics, and reads one in place", () => {
    at("/tables/find", <HelpPanel role="player" place="nav" />);
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const panel = screen.getByRole("dialog", { name: "Help" });
    const here = within(panel).getByRole("list", { name: "About this screen" });
    fireEvent.click(within(here).getByRole("button", { name: "Finding a table" }));
    expect(within(panel).getByRole("heading", { level: 2, name: "Finding a table" })).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "Open this topic on its own page" }).getAttribute("href")).toBe(
      "/help/find-a-table?lang=en",
    );
    fireEvent.click(
      within(panel).getByRole("button", {
        name: "Back to this screen's topics",
      }),
    );
    expect(within(panel).getByRole("list", { name: "About this screen" })).toBeTruthy();
  });

  it("keeps an organiser's topics from a player, and says when a screen has none", () => {
    at("/campaigns/cmp_1", <HelpPanel role="player" place="corner" />);
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const panel = screen.getByRole("dialog", { name: "Help" });
    expect(within(panel).queryByRole("button", { name: "Hosting a public game" })).toBeNull();
    expect(within(panel).getByText("There is no help about this screen yet.")).toBeTruthy();
    expect(within(panel).getByRole("link", { name: "All help" }).getAttribute("href")).toBe("/help?lang=en");
  });

  it("offers the basics of roleplaying on every screen, and walks on through Read next in the panel (DEL-285)", () => {
    at("/campaigns/cmp_1", <HelpPanel role="player" place="corner" />);
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const panel = screen.getByRole("dialog", { name: "Help" });
    fireEvent.click(within(panel).getByRole("button", { name: "Start here" }));
    expect(
      within(panel).getByRole("heading", {
        level: 2,
        name: "What a roleplaying game is",
      }),
    ).toBeTruthy();
    const next = within(panel).getByRole("navigation", { name: "Read next" });
    fireEvent.click(within(next).getByRole("button", { name: "The party and the DM" }));
    expect(
      within(panel).getByRole("heading", {
        level: 2,
        name: "The party and the DM",
      }),
    ).toBeTruthy();
  });

  it("doesn't offer the basics twice on a screen whose topics hold them", () => {
    at("/home", <HelpPanel role="player" place="nav" />);
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const panel = screen.getByRole("dialog", { name: "Help" });
    expect(within(panel).getByRole("button", { name: "What a roleplaying game is" })).toBeTruthy();
    expect(within(panel).queryByRole("button", { name: "Start here" })).toBeNull();
  });
});

describe("help in the reader's language (DEL-284)", () => {
  it("reads a translation's title, summary and text, keeping the English topic's place and links", () => {
    expect(parseTranslation("a", "---\ntitle: Titel\nsummary: Kort.\n---\nTekst.\n")).toEqual({
      title: "Titel",
      summary: "Kort.",
      body: "Tekst.",
    });
    expect(() => parseTranslation("b", "---\nsummary: Kort.\n---\n")).toThrow(/title/);
  });

  it("has every topic in every language, each with its pictures and links", async () => {
    for (const language of LANGUAGES.filter((each) => each !== "en")) {
      await loadTopics(language);
      for (const english of TOPICS) {
        const shown = inLanguage(english, language);
        expect(shown, `${language} ${english.slug} is translated`).not.toBe(english);
        const pictures = (body: string) => [...body.matchAll(/src="([^"]+)"/g)].map((m) => m[1]);
        const links = (body: string) => [...body.matchAll(/\]\((\/help\/[^)]+)\)/g)].map((m) => m[1]);
        expect(pictures(shown.body), `${language} ${english.slug}`).toEqual(pictures(english.body));
        expect(links(shown.body), `${language} ${english.slug}`).toEqual(links(english.body));
      }
    }
  });

  it("shows a help page in the language its link asks for", async () => {
    at("/help/what-is-delve?lang=nl", <HelpTopicPage />, "/help/:slug");
    await loadTopics("nl");
    const title = inLanguage(topic("what-is-delve")!, "nl").title;
    expect(await screen.findByRole("heading", { level: 1, name: title })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Hulp" })).toBeTruthy();
  });
});
