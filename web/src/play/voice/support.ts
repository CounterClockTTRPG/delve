/**
 * What this browser can do in voice (table voice and fixes Task V2.1): `talk` with the browser's own Opus encoder and a
 * microphone, `listen` with only its decoder (Safari and every iPhone browser, which have no encoder: there is no
 * bundled one), or `none`. Asking the encoder is a promise, so this is too.
 */

export type VoiceSupport = "talk" | "listen" | "none";

export const SAMPLE_RATE = 48000;

/** The pinned codec: Opus, mono, 48 kHz, 20 ms frames, 24 kbit/s. */
export const OPUS_ENCODER: AudioEncoderConfig = {
  codec: "opus",
  sampleRate: SAMPLE_RATE,
  numberOfChannels: 1,
  bitrate: 24000,
  opus: { frameDuration: 20000 },
} as AudioEncoderConfig;

export const OPUS_DECODER: AudioDecoderConfig = { codec: "opus", sampleRate: SAMPLE_RATE, numberOfChannels: 1 };

async function supported(check: (() => Promise<{ supported?: boolean }>) | undefined): Promise<boolean> {
  if (!check) return false;
  try {
    return (await check()).supported === true;
  } catch {
    return false;
  }
}

export async function voiceSupport(): Promise<VoiceSupport> {
  const encoder = globalThis.AudioEncoder as typeof AudioEncoder | undefined;
  const decoder = globalThis.AudioDecoder as typeof AudioDecoder | undefined;
  const listen =
    typeof globalThis.AudioWorkletNode === "function" &&
    (await supported(decoder && (() => decoder.isConfigSupported(OPUS_DECODER))));
  if (!listen) return "none";
  const talk =
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    (await supported(encoder && (() => encoder.isConfigSupported(OPUS_ENCODER))));
  return talk ? "talk" : "listen";
}
