/**
 * The microphone, encoded (table voice and fixes Task V2.1): `getUserMedia` with the browser's echo cancellation,
 * noise suppression and gain, tapped in 20 ms blocks by the `"delve-tap"` worklet, into the browser's own
 * `AudioEncoder` with the pinned Opus config, each packet framed for the relay. The speaking flag comes from the level
 * over the last 200 ms: above −45 dBFS, held 300 ms after it falls. Muted, the track is off and nothing is sent.
 *
 * One tap for every browser rather than `MediaStreamTrackProcessor` where there is one: the tap's context runs at
 * 48 kHz, so the encoder always gets what it was configured for.
 */
import { encodeFrame } from "./framing";
import { OPUS_ENCODER, SAMPLE_RATE } from "./support";

export const SPEAKING_DBFS = -45;
export const LEVEL_MS = 200;
export const HANG_MS = 300;
const BLOCK_MS = 20;

export interface Microphone {
  setMuted(muted: boolean): void;
  stop(): void;
}

/** Whether the last blocks' level says someone is speaking, with the hang. Plain, for the tests. */
export class SpeakingDetector {
  private squares: number[] = [];
  private samples: number[] = [];
  private loudAt = -Infinity;

  /** Feeds one block heard at `nowMs`, and answers whether this is speaking. */
  feed(block: Float32Array, nowMs: number): boolean {
    let sum = 0;
    for (const v of block) sum += v * v;
    this.squares.push(sum);
    this.samples.push(block.length);
    if (this.squares.length > LEVEL_MS / BLOCK_MS) {
      this.squares.shift();
      this.samples.shift();
    }
    const total = this.samples.reduce((a, b) => a + b, 0);
    const rms = Math.sqrt(this.squares.reduce((a, b) => a + b, 0) / total);
    if (rms > 0 && 20 * Math.log10(rms) > SPEAKING_DBFS) this.loudAt = nowMs;
    return nowMs - this.loudAt < HANG_MS;
  }
}

/** Opens the microphone on `context` (made at 48 kHz); `onFrame` gets each framed packet. Rejects when the
 * microphone is refused or missing. */
export async function startMicrophone(context: AudioContext, onFrame: (frame: ArrayBuffer) => void): Promise<Microphone> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const [track] = stream.getAudioTracks();
  const source = context.createMediaStreamSource(stream);
  const tap = new AudioWorkletNode(context, "delve-tap", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
  const detector = new SpeakingDetector();
  let muted = false;
  let speaking = false;
  let seq = 0;
  let timestamp = 0;
  const encoder = new AudioEncoder({
    output: (chunk) => {
      if (muted) return;
      const payload = new Uint8Array(chunk.byteLength);
      chunk.copyTo(payload);
      onFrame(encodeFrame({ speaking, seq: seq++, tsMs: Math.round(chunk.timestamp / 1000), payload }));
    },
    error: () => {},
  });
  encoder.configure(OPUS_ENCODER);
  tap.port.onmessage = (event: MessageEvent<Float32Array<ArrayBuffer>>) => {
    const block = event.data;
    speaking = !muted && detector.feed(block, performance.now());
    if (muted || encoder.state !== "configured") return;
    const data = new AudioData({
      format: "f32",
      sampleRate: SAMPLE_RATE,
      numberOfFrames: block.length,
      numberOfChannels: 1,
      timestamp,
      data: block,
    });
    timestamp += Math.round((block.length / SAMPLE_RATE) * 1_000_000);
    encoder.encode(data);
    data.close();
  };
  source.connect(tap);
  tap.connect(context.destination);
  return {
    setMuted(m) {
      muted = m;
      speaking = false;
      if (track) track.enabled = !m;
    },
    stop() {
      tap.port.onmessage = null;
      source.disconnect();
      tap.disconnect();
      if (encoder.state !== "closed") encoder.close();
      for (const t of stream.getTracks()) t.stop();
    },
  };
}
