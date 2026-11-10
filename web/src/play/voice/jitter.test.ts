import { describe, expect, it } from "vitest";
import { JitterBuffer, MAX_MS, TARGET_MS } from "./jitter";

const RATE = 48000;
const ms = (n: number) => Math.round((RATE * n) / 1000);

function filled(value: number, length: number): Float32Array {
  return new Float32Array(length).fill(value);
}

describe("JitterBuffer", () => {
  it("waits for the 60 ms target before it plays a slot", () => {
    expect(TARGET_MS).toBe(60);
    const buffer = new JitterBuffer(RATE);
    buffer.push(0, filled(0.5, ms(40)));
    const out = new Float32Array(128);
    buffer.mix(out);
    expect(out.every((v) => v === 0)).toBe(true);
    buffer.push(0, filled(0.5, ms(20)));
    buffer.mix(out);
    expect(out.every((v) => v === 0.5)).toBe(true);
  });

  it("drops the oldest samples past 200 ms", () => {
    expect(MAX_MS).toBe(200);
    const buffer = new JitterBuffer(RATE);
    buffer.push(0, filled(0.1, ms(100)));
    buffer.push(0, filled(0.2, ms(150)));
    expect(buffer.buffered(0)).toBe(ms(200));
    const out = new Float32Array(128);
    buffer.mix(out);
    expect(out[0], "the oldest 50 ms of the first packet went").toBeCloseTo(0.1);
    // 50 ms of 0.1 is left, then 0.2.
    const rest = new Float32Array(ms(50));
    buffer.mix(rest);
    expect(rest[rest.length - 1]).toBeCloseTo(0.2);
  });

  it("mixes two slots by sum, clipped to ±1", () => {
    const buffer = new JitterBuffer(RATE);
    buffer.push(0, filled(0.25, ms(60)));
    buffer.push(1, filled(0.5, ms(60)));
    const out = new Float32Array(128);
    buffer.mix(out);
    expect(out[0]).toBeCloseTo(0.75);
    buffer.push(0, filled(0.75, ms(60)));
    buffer.push(1, filled(0.75, ms(60)));
    const loud = new Float32Array(ms(120));
    buffer.mix(loud);
    expect(Math.max(...loud)).toBe(1);
    buffer.push(2, filled(-0.8, ms(60)));
    buffer.push(3, filled(-0.8, ms(60)));
    const low = new Float32Array(128);
    buffer.mix(low);
    expect(low[0]).toBe(-1);
  });

  it("waits for the target again after a slot ran dry", () => {
    const buffer = new JitterBuffer(RATE);
    buffer.push(0, filled(0.5, ms(60)));
    buffer.mix(new Float32Array(ms(60)));
    buffer.push(0, filled(0.5, ms(20)));
    const out = new Float32Array(128);
    buffer.mix(out);
    expect(out.every((v) => v === 0)).toBe(true);
  });

  it("forgets a slot", () => {
    const buffer = new JitterBuffer(RATE);
    buffer.push(0, filled(0.5, ms(80)));
    buffer.forget(0);
    expect(buffer.buffered(0)).toBe(0);
  });
});
