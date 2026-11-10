import { describe, expect, it } from "vitest";
import { decodeRelayed, encodeFrame } from "./framing";

/** The relay prefixes a client's frame with the sender's slot. */
function relayed(slot: number, frame: ArrayBuffer): ArrayBuffer {
  const out = new Uint8Array(frame.byteLength + 1);
  out[0] = slot;
  out.set(new Uint8Array(frame), 1);
  return out.buffer;
}

describe("voice framing", () => {
  it("round-trips a frame through the relay's slot prefix", () => {
    const payload = new Uint8Array([9, 8, 7, 6]);
    const frame = encodeFrame({ speaking: true, seq: 513, tsMs: 123456, payload });
    expect(frame.byteLength).toBe(8 + payload.length);
    expect(decodeRelayed(relayed(3, frame))).toEqual({ slot: 3, speaking: true, seq: 513, tsMs: 123456, payload });
  });

  it("writes the header big-endian, version 1 and the speaking bit", () => {
    const frame = new Uint8Array(encodeFrame({ speaking: true, seq: 0x0102, tsMs: 0x01020304, payload: new Uint8Array([0xff]) }));
    expect(Array.from(frame)).toEqual([1, 1, 0x01, 0x02, 0x01, 0x02, 0x03, 0x04, 0xff]);
    const quiet = new Uint8Array(encodeFrame({ speaking: false, seq: 0, tsMs: 0, payload: new Uint8Array([0]) }));
    expect(quiet[1]).toBe(0);
  });

  it("wraps the sequence number and the timestamp", () => {
    const frame = encodeFrame({ speaking: false, seq: 0x10001, tsMs: 2 ** 32 + 5, payload: new Uint8Array([1]) });
    const back = decodeRelayed(relayed(0, frame));
    expect(back.seq).toBe(1);
    expect(back.tsMs).toBe(5);
  });

  it("refuses another version and a frame too short to hold a packet", () => {
    const frame = new Uint8Array(encodeFrame({ speaking: false, seq: 1, tsMs: 1, payload: new Uint8Array([1]) }));
    frame[0] = 2;
    expect(() => decodeRelayed(relayed(0, frame.buffer))).toThrow();
    expect(() => decodeRelayed(new Uint8Array(9).buffer)).toThrow();
  });
});
