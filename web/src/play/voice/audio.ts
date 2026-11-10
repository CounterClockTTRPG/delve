/**
 * The audio context voice plays and taps in (table voice and fixes Task V2.2): 48 kHz, the pinned codec's rate, with
 * the voice worklets added. Made inside Join, so the browser lets it start.
 */
import workletUrl from "./jitter.worklet.ts?worker&url";
import { SAMPLE_RATE } from "./support";

export async function openAudio(): Promise<AudioContext> {
  const context = new AudioContext({ sampleRate: SAMPLE_RATE, latencyHint: "interactive" });
  try {
    await context.audioWorklet.addModule(workletUrl);
    await context.resume();
  } catch (error) {
    void context.close();
    throw error;
  }
  return context;
}
