import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RECONNECTED, sharedEvents } from "./api";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static CLOSED = 2;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  readyState = 1;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data?: unknown) {
    for (const fn of this.listeners[type] ?? []) fn(new MessageEvent(type, { data: JSON.stringify(data ?? null) }));
  }
}

let meStatus: number;

beforeEach(() => {
  FakeEventSource.instances = [];
  meStatus = 200;
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: meStatus })));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Closes the newest stream the way a browser that gave up does, and lets `/api/me` answer. */
async function giveUp() {
  const stream = FakeEventSource.instances.at(-1)!;
  stream.readyState = FakeEventSource.CLOSED;
  stream.emit("error");
  await vi.advanceTimersByTimeAsync(0);
}

describe("sharedEvents", () => {
  it("opens a new stream after a closed one, waiting longer each time, and says it is back", async () => {
    const events = sharedEvents("cmp_00000000000a");
    const beats: unknown[] = [];
    const back = vi.fn();
    events.subscribe({ beat: (data) => beats.push(data), [RECONNECTED]: back });
    expect(FakeEventSource.instances).toHaveLength(1);

    await giveUp();
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeEventSource.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(FakeEventSource.instances[1].url).toBe("/api/events?campaign=cmp_00000000000a");

    // Still down: the next wait is twice as long.
    await giveUp();
    await vi.advanceTimersByTimeAsync(1999);
    expect(FakeEventSource.instances).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeEventSource.instances).toHaveLength(3);

    const stream = FakeEventSource.instances[2];
    stream.emit("open");
    expect(back).toHaveBeenCalledTimes(1);
    stream.emit("beat", { id: "beat_1" });
    expect(beats).toEqual([{ id: "beat_1" }]);
    events.close();
  });

  it("calls the lost listeners and opens nothing when Delve no longer knows this browser", async () => {
    const events = sharedEvents();
    const lost = vi.fn();
    events.onLost(lost);
    events.subscribe({ beat: () => {} });
    meStatus = 401;
    await giveUp();
    expect(lost).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("opens nothing more once closed", async () => {
    const events = sharedEvents();
    events.subscribe({ beat: () => {} });
    await giveUp();
    events.close();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
