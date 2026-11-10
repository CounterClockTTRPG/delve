/**
 * The listener's jitter buffer (table voice and fixes Task V2.1), run by `jitter.worklet.ts`: one buffer per sender's
 * slot, played once it holds the 60 ms target, at most 200 ms (older samples are dropped), every slot mixed into the
 * one output by sum, clipped to ±1. A plain class, so the tests run it without an audio thread.
 */

export const TARGET_MS = 60;
export const MAX_MS = 200;

interface Slot {
  chunks: Float32Array[];
  /** Samples already played from `chunks[0]`. */
  offset: number;
  length: number;
  playing: boolean;
}

export class JitterBuffer {
  private slots = new Map<number, Slot>();
  private readonly target: number;
  private readonly max: number;

  constructor(sampleRate: number) {
    this.target = Math.round((sampleRate * TARGET_MS) / 1000);
    this.max = Math.round((sampleRate * MAX_MS) / 1000);
  }

  push(slot: number, pcm: Float32Array): void {
    let found = this.slots.get(slot);
    if (!found) this.slots.set(slot, (found = { chunks: [], offset: 0, length: 0, playing: false }));
    found.chunks.push(pcm);
    found.length += pcm.length;
    this.drop(found, found.length - this.max);
    if (found.length >= this.target) found.playing = true;
  }

  forget(slot: number): void {
    this.slots.delete(slot);
  }

  buffered(slot: number): number {
    return this.slots.get(slot)?.length ?? 0;
  }

  /** Fills `out` with every playing slot's next samples, summed and clipped. */
  mix(out: Float32Array): void {
    out.fill(0);
    for (const slot of this.slots.values()) {
      if (!slot.playing) continue;
      let at = 0;
      while (at < out.length && slot.chunks.length > 0) {
        const chunk = slot.chunks[0];
        const n = Math.min(out.length - at, chunk.length - slot.offset);
        for (let i = 0; i < n; i++) out[at + i] += chunk[slot.offset + i];
        at += n;
        slot.offset += n;
        slot.length -= n;
        if (slot.offset === chunk.length) {
          slot.chunks.shift();
          slot.offset = 0;
        }
      }
      if (slot.length === 0) slot.playing = false;
    }
    for (let i = 0; i < out.length; i++) out[i] = Math.max(-1, Math.min(1, out[i]));
  }

  private drop(slot: Slot, samples: number): void {
    while (samples > 0 && slot.chunks.length > 0) {
      const left = slot.chunks[0].length - slot.offset;
      const n = Math.min(samples, left);
      slot.offset += n;
      slot.length -= n;
      samples -= n;
      if (slot.offset === slot.chunks[0].length) {
        slot.chunks.shift();
        slot.offset = 0;
      }
    }
  }
}
