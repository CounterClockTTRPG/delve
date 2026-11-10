/**
 * Voice frames on the wire (table voice and fixes Task V2.1), as the relay's protocol pins them: a client sends an
 * 8-byte header (version 1, flags with bit 0 speaking, a uint16 sequence number and a uint32 timestamp in
 * milliseconds, both big-endian and wrapping) and one Opus packet; the relay forwards it to the others with one byte
 * in front, the sender's slot.
 */

export const VERSION = 1;
export const HEADER_BYTES = 8;

export interface OutgoingFrame {
  speaking: boolean;
  seq: number;
  tsMs: number;
  payload: Uint8Array;
}

export interface RelayedFrame extends OutgoingFrame {
  slot: number;
}

export function encodeFrame(f: OutgoingFrame): ArrayBuffer {
  const out = new ArrayBuffer(HEADER_BYTES + f.payload.length);
  const view = new DataView(out);
  view.setUint8(0, VERSION);
  view.setUint8(1, f.speaking ? 1 : 0);
  view.setUint16(2, f.seq & 0xffff);
  view.setUint32(4, f.tsMs % 2 ** 32);
  new Uint8Array(out, HEADER_BYTES).set(f.payload);
  return out;
}

/** A frame as the relay sends it; throws on another version or a frame with no packet. */
export function decodeRelayed(data: ArrayBuffer): RelayedFrame {
  if (data.byteLength < 1 + HEADER_BYTES + 1) throw new Error(`a relayed voice frame of ${data.byteLength} bytes`);
  const view = new DataView(data);
  const version = view.getUint8(1);
  if (version !== VERSION) throw new Error(`voice frame version ${version}`);
  return {
    slot: view.getUint8(0),
    speaking: (view.getUint8(2) & 1) === 1,
    seq: view.getUint16(3),
    tsMs: view.getUint32(5),
    payload: new Uint8Array(data.slice(1 + HEADER_BYTES)),
  };
}
