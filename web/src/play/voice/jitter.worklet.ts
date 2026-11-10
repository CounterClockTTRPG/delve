/**
 * The voice worklets (table voice and fixes Task V2.1), loaded with `audioWorklet.addModule`; bundled on its own, so it
 * exports nothing.
 *
 * - `"delve-jitter"` plays what the others say: the main thread posts `{slot, pcm}` (a decoded packet) and
 *   `{forget: slot}` (a peer that left), and `JitterBuffer` mixes every slot into the output.
 * - `"delve-tap"` hands the microphone to the encoder: 20 ms blocks of its first channel, posted to the main thread.
 *   Its output is silence; it is connected only so the audio thread runs it.
 */
import { JitterBuffer } from "./jitter";

declare const sampleRate: number;
declare function registerProcessor(name: string, processor: unknown): void;
declare const AudioWorkletProcessor: { new (): { readonly port: MessagePort } };

class DelveJitter extends AudioWorkletProcessor {
  private buffer = new JitterBuffer(sampleRate);

  constructor() {
    super();
    this.port.onmessage = (event: MessageEvent<{ slot: number; pcm: Float32Array } | { forget: number }>) => {
      if ("forget" in event.data) this.buffer.forget(event.data.forget);
      else this.buffer.push(event.data.slot, event.data.pcm);
    };
  }

  process(_inputs: Float32Array[][], outputs: Float32Array[][]): boolean {
    const [channel, ...others] = outputs[0];
    if (channel) {
      this.buffer.mix(channel);
      for (const other of others) other.set(channel);
    }
    return true;
  }
}

class DelveTap extends AudioWorkletProcessor {
  private readonly size = Math.round(sampleRate / 50);
  private block = new Float32Array(this.size);
  private filled = 0;

  process(inputs: Float32Array[][]): boolean {
    const input = inputs[0]?.[0];
    if (!input) return true;
    let at = 0;
    while (at < input.length) {
      const n = Math.min(input.length - at, this.size - this.filled);
      this.block.set(input.subarray(at, at + n), this.filled);
      this.filled += n;
      at += n;
      if (this.filled === this.size) {
        // Transferred, the block is gone from here: a new one for the next 20 ms.
        this.port.postMessage(this.block, [this.block.buffer]);
        this.block = new Float32Array(this.size);
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor("delve-jitter", DelveJitter);
registerProcessor("delve-tap", DelveTap);
