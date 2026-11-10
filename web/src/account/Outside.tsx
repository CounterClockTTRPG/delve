import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useT } from "../i18n";
import { accountKeys, getAuthProviders, outsideStartUrl, type OutsideMode } from "./api";

/** What came back from an outside login (DEL-206): `?oidc=<code>` (and a sign-up's `username`), read once and taken
 * off the address, so a reload doesn't say it again. */
export function useOutsideResult(): { code: string | null; username: string | null } {
  const [result] = useState(() => {
    if (typeof window === "undefined") return { code: null, username: null };
    const params = new URLSearchParams(window.location.search);
    const code = params.get("oidc");
    const username = params.get("username");
    if (code) {
      params.delete("oidc");
      params.delete("username");
      const rest = params.toString();
      window.history.replaceState(null, "", `${window.location.pathname}${rest ? `?${rest}` : ""}${window.location.hash}`);
    }
    return { code, username };
  });
  return result;
}

/** The sentence for an outside login's code, in the reader's language; null for a code the dictionaries lack. */
export function sayOutside(t: ReturnType<typeof useT>, code: string, title = "Google"): string | null {
  const key = `outside.${code}`;
  const said = t(key, { provider: title });
  return said === key ? null : said;
}

/**
 * The "Continue with …" buttons of the providers this browser may use (none: nothing shown). Each sends the browser
 * to the provider, through Delve's start; `params` go with it (a sign-up's username, the page to come back to).
 */
export function OutsideButtons({
  mode,
  params = {},
  disabled = false,
  label = "outside.continue",
}: {
  mode: OutsideMode;
  params?: Record<string, string>;
  disabled?: boolean;
  label?: string;
}) {
  const t = useT();
  const providers = useQuery({ queryKey: accountKeys.authProviders, queryFn: getAuthProviders, retry: false, staleTime: 60_000 });
  if (!providers.data?.length) return null;
  return (
    <div className="outside-logins" data-testid="outside-logins">
      {providers.data.map((provider) => (
        <button
          key={provider.id}
          type="button"
          className="outside-login"
          data-testid={`outside-${provider.id}`}
          disabled={disabled}
          onClick={() => window.location.assign(outsideStartUrl(provider.id, mode, params))}
        >
          {t(label, { provider: provider.title })}
        </button>
      ))}
    </div>
  );
}
