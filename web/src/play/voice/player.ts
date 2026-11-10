/**
 * What the others say, played (table voice and fixes Task V2.1): one `AudioDecoder` per sender's slot, each decoded
 * packet posted to the `"delve-jitter"` worklet, which buffers and mixes them into the speakers. Nothing is kept.
 */
import type { RelayedFrame } from "./framing";
import { OPUS_DECODER } from "./support";

export interface Player {
  push(relayed: RelayedFrame): void;
  /** A peer left: its decoder and its buffered samples go. */
  forget(slot: number): void;
  stop(): void;
}

/** Plays into `context` (made at 48 kHz, with the voice worklets added). */
export async function startPlayer(context: AudioContext): Promise<Player> {
  const node = new AudioWorkletNode(context, "delve-jitter", { numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1] });
  node.connect(context.destination);
  const decoders = new Map<number, AudioDecoder>();
  const decoder = (slot: number) => {
    let found = decoders.get(slot);
    if (!found) {
      found = new AudioDecoder({
        output: (data) => {
          const pcm = new Float32Array(data.numberOfFrames);
          data.copyTo(pcm, { planeIndex: 0, format: "f32-planar" });
          data.close();
          node.port.postMessage({ slot, pcm }, [pcm.buffer]);
        },
        error: () => decoders.delete(slot),
      });
      found.configure(OPUS_DECODER);
      decoders.set(slot, found);
    }
    return found;
  };
  const close = (slot: number) => {
    const found = decoders.get(slot);
    decoders.delete(slot);
    if (found && found.state !== "closed") found.close();
  };
  return {
    push(relayed) {
      const target = decoder(relayed.slot);
      if (target.state !== "configured") return;
      target.decode(new EncodedAudioChunk({ type: "key", timestamp: relayed.tsMs * 1000, data: relayed.payload }));
    },
    forget(slot) {
      close(slot);
      node.port.postMessage({ forget: slot });
    },
    stop() {
      for (const slot of [...decoders.keys()]) close(slot);
      node.disconnect();
    },
  };
}
