// The owner token: the link Delve prints carries it as `#token=…`. The page takes it out of the address bar at once,
// so it isn't shared by copying the URL, and posts it once to the server, which keeps it in an HttpOnly cookie that
// no script on the page can read (DEL-154, audit finding 9). A browser that still has the cookie the page itself
// wrote before hands that over the same way, once; one the server doesn't take is dropped.
import { ApiError, NeedsToken, postJson } from "./api";

export const TOKEN_COOKIE = "delve_token";

/** The token in a cookie a script can read: only the page's own of before DEL-154; the server's is HttpOnly. */
export function readTokenCookie(): string | null {
  for (const part of document.cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === TOKEN_COOKIE && rest.length) {
      const value = decodeURIComponent(rest.join("="));
      return value || null;
    }
  }
  return null;
}

function dropTokenCookie(): void {
  document.cookie = `${TOKEN_COOKIE}=; Path=/; SameSite=Strict; Max-Age=0`;
}

/** Takes `#token=…` out of the URL; the token, or null if the URL had none. */
function tokenFromUrl(): string | null {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token");
  if (!token) return null;
  params.delete("token");
  const rest = params.toString();
  history.replaceState(history.state, "", location.pathname + location.search + (rest ? `#${rest}` : ""));
  return token;
}

/** Before anything calls the API: the link's token (or an old script-readable cookie's) goes to the server, which
 * answers with the HttpOnly cookie. Never fails: without the cookie, the page shows the login. */
export async function takeTokenFromUrl(): Promise<void> {
  const fromUrl = tokenFromUrl();
  const old = fromUrl ? null : readTokenCookie();
  const token = fromUrl ?? old;
  if (!token) return;
  try {
    await postJson("/api/owner-token/cookie", { token });
  } catch (error) {
    // Refused (a token made anew since, or through a tunnel): a script's cookie of it is no use. A network failure
    // keeps it for the next load.
    if (old && (error instanceof NeedsToken || error instanceof ApiError)) dropTokenCookie();
  }
}

export interface NewOwnerToken {
  token: string;
  /** The links that open Delve with it: one per LAN address, then this machine's. */
  links: string[];
}

/** A new owner token, the old one refused at once (the owner's alone). */
export const newOwnerToken = () => postJson<NewOwnerToken>("/api/owner-token/new");
