import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOKEN_COOKIE, readTokenCookie, takeTokenFromUrl } from "./token";

function clearCookie() {
  document.cookie = `${TOKEN_COOKIE}=; Path=/; Max-Age=0`;
}

function json(status: number, body: unknown = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

let fetchMock: ReturnType<typeof vi.fn>;
let answer: () => Response | Promise<Response>;

beforeEach(() => {
  answer = () => json(204);
  fetchMock = vi.fn(async () => answer());
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearCookie();
  history.replaceState(null, "", "/");
});

function posted(): unknown[] {
  return fetchMock.mock.calls.map(([path, init]) => {
    expect(path).toBe("/api/owner-token/cookie");
    expect(init.method).toBe("POST");
    return JSON.parse(String(init.body));
  });
}

// DEL-154, audit finding 9: the server keeps the token in an HttpOnly cookie; the page never writes one.
describe("token", () => {
  it("posts the link's token once and strips it from the URL", async () => {
    history.replaceState(null, "", "/preferences?x=1#token=abc123");
    await takeTokenFromUrl();
    expect(posted()).toEqual([{ token: "abc123" }]);
    expect(location.hash).toBe("");
    expect(location.pathname + location.search).toBe("/preferences?x=1");
    expect(readTokenCookie()).toBeNull();
  });

  it("strips the URL before the server answers", async () => {
    let release: (r: Response) => void = () => {};
    answer = () => new Promise<Response>((resolve) => (release = resolve));
    history.replaceState(null, "", "/#token=t0");
    const done = takeTokenFromUrl();
    expect(location.hash).toBe("");
    release(json(204));
    await done;
  });

  it("keeps other hash parts", async () => {
    history.replaceState(null, "", "/#token=t1&room=3");
    await takeTokenFromUrl();
    expect(posted()).toEqual([{ token: "t1" }]);
    expect(location.hash).toBe("#room=3");
  });

  it("leaves the URL alone and asks nothing without a token", async () => {
    history.replaceState(null, "", "/maps#other");
    await takeTokenFromUrl();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(location.hash).toBe("#other");
  });

  it("hands over a token the page kept in a script's cookie before", async () => {
    document.cookie = `${TOKEN_COOKIE}=old%20one; Path=/`;
    await takeTokenFromUrl();
    expect(posted()).toEqual([{ token: "old one" }]);
  });

  it("drops a script's cookie the server doesn't take", async () => {
    document.cookie = `${TOKEN_COOKIE}=stale; Path=/`;
    answer = () => json(401, { error: "That isn't the owner token: ask for a new link." });
    await takeTokenFromUrl();
    expect(readTokenCookie()).toBeNull();
  });

  it("keeps a script's cookie when the server can't be reached", async () => {
    document.cookie = `${TOKEN_COOKIE}=kept; Path=/`;
    answer = () => Promise.reject(new TypeError("Failed to fetch"));
    await takeTokenFromUrl();
    expect(readTokenCookie()).toBe("kept");
  });

  it("never writes the cookie itself", async () => {
    const writes: string[] = [];
    const desc = Object.getOwnPropertyDescriptor(Document.prototype, "cookie")!;
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => desc.get!.call(document),
      set: (v: string) => {
        writes.push(v);
        desc.set!.call(document, v);
      },
    });
    try {
      history.replaceState(null, "", "/#token=abc");
      await takeTokenFromUrl();
    } finally {
      delete (document as unknown as Record<string, unknown>).cookie;
    }
    expect(writes).toEqual([]);
  });
});
