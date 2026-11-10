// Test helpers for the board's pages: who reads, a zone, a topic and its posts as the server answers them, and the
// pages under their frame at an address.
import { render } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { json } from "../play/testing";
import type { Author, BoardZone, Post, Topic, TopicPage as Shown, Zone, ZoneRights } from "./api";
import BoardFrame from "./BoardFrame";
import BoardIndex from "./BoardIndex";
import TopicPage from "./TopicPage";
import ZonePage from "./ZonePage";

export const ANA = "acc_00000000000a";
export const BOB = "acc_00000000000b";

/** `GET /api/me` for an account, or a visitor's 401. */
export const asAccount = (id = ANA) => () =>
  json(200, {
    account: { id, username: "ana", display_name: "Ana", language: "en", organiser: false, owner: false },
    seat: null,
    principal: { id, roles: ["player"] },
  });
export const asVisitor = () => json(401, { error: "Log in." });

export const rights = (overrides: Partial<ZoneRights> = {}): ZoneRights => ({
  read: true,
  write: true,
  moderate: false,
  manage: false,
  manage_wide: false,
  ...overrides,
});

export function zone(overrides: Partial<Zone> = {}): Zone {
  return {
    id: "zon_00000000000a",
    name: "The engine",
    description: "How Delve plays.",
    position: 0,
    read: "everybody",
    write: "accounts",
    pictures: false,
    campaign_id: null,
    rights: rights(),
    ...overrides,
  };
}

export const boardZone = (overrides: Partial<BoardZone> = {}): BoardZone => ({ ...zone(), topics: 0, new_topics: 0, latest: null, ...overrides });

export function author(overrides: Partial<Author> = {}): Author {
  return { account_id: ANA, display_name: "Ana", avatar: { emblem: "dragon" }, colour: "teal", badges: [], ...overrides };
}

export function topic(overrides: Partial<Topic> = {}): Topic {
  return {
    id: "top_00000000000a",
    zone_id: "zon_00000000000a",
    title: "Could the DM roll morale in the open?",
    author: author(),
    created_at: "2026-10-28T20:14:00Z",
    last_post_at: "2026-10-28T21:02:00Z",
    last_author: author(),
    posts: 1,
    pinned: false,
    locked: false,
    new: false,
    ...overrides,
  };
}

export function post(id: string, overrides: Partial<Post> = {}): Post {
  return {
    id,
    topic_id: "top_00000000000a",
    author: author(),
    text: "When the goblins break, we only see **they flee**.",
    created_at: "2026-10-28T20:14:00Z",
    edited_at: null,
    removed: null,
    picture: null,
    mine: false,
    ...overrides,
  };
}

export function topicPage(posts: Post[], overrides: Partial<Shown> = {}): Shown {
  return {
    zone: zone(),
    topic: topic({ posts: posts.length }),
    posts,
    page: 1,
    pages: 1,
    first_unread_page: 1,
    first_unread_post: null,
    ...overrides,
  };
}

/** The board's pages under their frame, at `path`. */
export function renderBoard(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/board" element={<BoardFrame />}>
          <Route index element={<BoardIndex />} />
          <Route path=":zoneId" element={<ZonePage />} />
          <Route path=":zoneId/:topicId" element={<TopicPage />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}
