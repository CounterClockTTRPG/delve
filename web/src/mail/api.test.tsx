import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getMailStatus, useMailEnabled } from "./api";

function answer(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })),
  );
}

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

afterEach(() => vi.unstubAllGlobals());

describe("mail status", () => {
  it("reads the flag", async () => {
    answer({ enabled: true });
    expect(await getMailStatus()).toEqual({ enabled: true });
  });

  it("useMailEnabled is false until the server says yes", async () => {
    answer({ enabled: true });
    const { result } = renderHook(() => useMailEnabled(), { wrapper });
    expect(result.current).toBe(false);
    await waitFor(() => expect(result.current).toBe(true));
  });

  it("useMailEnabled stays false when the status can't be read", async () => {
    answer({ error: "no" }, 500);
    const { result } = renderHook(() => useMailEnabled(), { wrapper });
    await new Promise((r) => setTimeout(r, 50));
    expect(result.current).toBe(false);
  });
});
