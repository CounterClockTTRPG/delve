import { describe, expect, it } from "vitest";
import { HANG_MS, SpeakingDetector } from "./encoder";

const block = (value: number) => new Float32Array(960).fill(value);

describe("SpeakingDetector", () => {
  it("speaks above −45 dBFS and holds it 300 ms after it falls", () => {
    const detector = new SpeakingDetector();
    expect(detector.feed(block(0), 0), "silence").toBe(false);
    expect(detector.feed(block(0.001), 20), "−60 dBFS is quiet").toBe(false);
    expect(detector.feed(block(0.1), 40), "−20 dBFS").toBe(true);
    // The loud block stays in the 200 ms window (ten blocks) until 220 ms; the hang holds 300 ms past that.
    for (let now = 60; now <= 500; now += 20) expect(detector.feed(block(0), now), `${now} ms`).toBe(true);
    expect(detector.feed(block(0), 220 + HANG_MS)).toBe(false);
  });
});
