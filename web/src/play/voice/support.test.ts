import { afterEach, describe, expect, it, vi } from "vitest";
import { voiceSupport } from "./support";

function stubAll({ encoder, decoder, mic, worklet }: { encoder: boolean; decoder: boolean; mic: boolean; worklet: boolean }) {
  vi.stubGlobal("AudioEncoder", encoder ? { isConfigSupported: async () => ({ supported: true }) } : undefined);
  vi.stubGlobal("AudioDecoder", decoder ? { isConfigSupported: async () => ({ supported: true }) } : undefined);
  vi.stubGlobal("AudioWorkletNode", worklet ? function AudioWorkletNode() {} : undefined);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: mic ? { getUserMedia: vi.fn() } : undefined,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: undefined });
});

describe("voiceSupport", () => {
  it("talks with an Opus encoder, a microphone, a decoder and worklets", async () => {
    stubAll({ encoder: true, decoder: true, mic: true, worklet: true });
    expect(await voiceSupport()).toBe("talk");
  });

  it("only listens without an encoder (Safari) or without a microphone", async () => {
    stubAll({ encoder: false, decoder: true, mic: true, worklet: true });
    expect(await voiceSupport()).toBe("listen");
    stubAll({ encoder: true, decoder: true, mic: false, worklet: true });
    expect(await voiceSupport()).toBe("listen");
  });

  it("can't without a decoder or worklets", async () => {
    stubAll({ encoder: true, decoder: false, mic: true, worklet: true });
    expect(await voiceSupport()).toBe("none");
    stubAll({ encoder: true, decoder: true, mic: true, worklet: false });
    expect(await voiceSupport()).toBe("none");
  });

  it("only listens when the encoder doesn't take Opus", async () => {
    stubAll({ encoder: true, decoder: true, mic: true, worklet: true });
    vi.stubGlobal("AudioEncoder", { isConfigSupported: async () => ({ supported: false }) });
    expect(await voiceSupport()).toBe("listen");
  });
});
