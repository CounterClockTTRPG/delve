// Test helpers for voice: a fake socket, a fake microphone and the browser's audio globals, stubbed.
import { act } from "@testing-library/react";
import { vi } from "vitest";

/** WebSocket, as far as useVoice uses it; `open` lists the live ones. */
export class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static open: FakeWebSocket[] = [];
  readyState = FakeWebSocket.CONNECTING;
  binaryType = "blob";
  bufferedAmount = 0;
  sent: (string | ArrayBuffer)[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.open.push(this);
  }

  send(data: string | ArrayBuffer) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.readyState = FakeWebSocket.CLOSED;
    FakeWebSocket.open = FakeWebSocket.open.filter((s) => s !== this);
    void code;
  }

  /** The text messages sent, parsed. */
  messages(): Record<string, unknown>[] {
    return this.sent.filter((m): m is string => typeof m === "string").map((m) => JSON.parse(m));
  }

  accept(welcome: Record<string, unknown> = {}) {
    act(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.();
      this.receive({ type: "welcome", you: "seat_00000000000h", slot: 0, talk: true, peers: [], limits: {}, ...welcome });
    });
  }

  receive(message: Record<string, unknown> | ArrayBuffer) {
    act(() => this.onmessage?.({ data: message instanceof ArrayBuffer ? message : JSON.stringify(message) }));
  }

  serverClose(code: number) {
    act(() => {
      this.readyState = FakeWebSocket.CLOSED;
      FakeWebSocket.open = FakeWebSocket.open.filter((s) => s !== this);
      this.onclose?.({ code });
    });
  }
}

export interface FakeMic {
  getUserMedia: ReturnType<typeof vi.fn>;
  track: { enabled: boolean; stop: ReturnType<typeof vi.fn> };
}

/** Stubs what voice needs of the browser: a talking browser when `encoder`, a microphone that `refuse`s or not. */
export function stubVoiceBrowser({ encoder = true, refuse = false }: { encoder?: boolean; refuse?: boolean } = {}): FakeMic {
  const track = { enabled: true, stop: vi.fn() };
  const getUserMedia = vi.fn(async () => {
    if (refuse) throw new DOMException("refused", "NotAllowedError");
    return { getAudioTracks: () => [track], getTracks: () => [track] };
  });
  const codec = { isConfigSupported: async () => ({ supported: true }) };
  vi.stubGlobal("AudioDecoder", codec);
  vi.stubGlobal(
    "AudioEncoder",
    encoder
      ? Object.assign(
          class {
            state = "unconfigured";
            configure() {
              this.state = "configured";
            }
            encode() {}
            close() {
              this.state = "closed";
            }
          },
          codec,
        )
      : undefined,
  );
  vi.stubGlobal(
    "AudioWorkletNode",
    class {
      port = { onmessage: null, postMessage: () => {} };
      connect() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("WebSocket", FakeWebSocket);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  FakeWebSocket.open = [];
  return { getUserMedia, track };
}

export function unstubVoiceBrowser() {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
}

/** What `openAudio` answers in the tests: a context the microphone and the player can be wired to. */
export function fakeContext(): AudioContext {
  const node = { connect: () => {}, disconnect: () => {} };
  return {
    destination: {},
    createMediaStreamSource: () => node,
    close: async () => {},
  } as unknown as AudioContext;
}
