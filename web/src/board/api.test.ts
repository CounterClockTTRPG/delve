import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attachPicture, getTopic, postAvatarUrl, postPictureUrl, reorderZones, startTopic } from "./api";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  fetchMock.mockReset();
});

const lastCall = () => {
  const [path, init] = fetchMock.mock.calls.at(-1)!;
  return { path: path as string, init: init as RequestInit };
};

describe("board api", () => {
  it("asks for a page of a topic only when one is named", async () => {
    await getTopic("t 1");
    expect(lastCall().path).toBe("/api/board/topics/t%201");
    await getTopic("t1", 3);
    expect(lastCall().path).toBe("/api/board/topics/t1?page=3");
  });

  it("sends a new topic's title and text, and the zones' order, as the server reads them", async () => {
    await startTopic("z1", "Hello", "Body");
    expect(lastCall().path).toBe("/api/board/zones/z1/topics");
    expect(lastCall().init.method).toBe("POST");
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ title: "Hello", text: "Body" });
    await reorderZones(["b", "a"]);
    expect(lastCall().init.method).toBe("PUT");
    expect(JSON.parse(lastCall().init.body as string)).toEqual({ zone_ids: ["b", "a"] });
  });

  it("sends a picture as the raw body, in its own type", async () => {
    const file = new File(["x"], "p.png", { type: "image/png" });
    await attachPicture("p1", file);
    const { path, init } = lastCall();
    expect(path).toBe("/api/board/posts/p1/picture");
    expect(init.body).toBe(file);
    expect(new Headers(init.headers).get("Content-Type")).toBe("image/png");
  });

  it("serves a post's picture and its author's avatar by the post", () => {
    expect(postPictureUrl("p1")).toBe("/api/board/posts/p1/picture");
    expect(postAvatarUrl("p1")).toBe("/api/board/posts/p1/avatar");
  });
});
