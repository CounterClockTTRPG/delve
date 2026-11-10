/**
 * The play screen's voice connection (table voice and fixes Task V2.2), over the relay's socket
 * (`/api/campaigns/{id}/voice`, the protocol pinned in the plan). Joining means listening; the microphone is asked
 * for only inside `join()`, and a refused or missing one joins listening only, as an observer and a browser with no
 * encoder always do. A dropped socket is tried again after 1 s, 2 s and 5 s, then the state is `error` (`lost`). The
 * server's `bye` ends it: `off` (the host switched voice off) hides the controls until voice is allowed again.
 * Nothing is recorded; audio goes from the microphone to the socket and from the socket to the speakers.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { SeatRole } from "../api";
import { openAudio } from "./audio";
import { startMicrophone, type Microphone } from "./encoder";
import { decodeRelayed } from "./framing";
import { startPlayer, type Player } from "./player";
import { voiceSupport, type VoiceSupport } from "./support";

export interface VoicePeer {
  slot: number;
  name: string;
  talk: boolean;
  muted: boolean;
  listening_only: boolean;
  speaking: boolean;
}

export type VoiceStatus = "off" | "joining" | "in" | "error";

export interface VoiceState {
  /** False when the campaign's voice is off: no controls. */
  allowed: boolean;
  /** What this browser can do; null while it is being asked. */
  support: VoiceSupport | null;
  status: VoiceStatus;
  /** Why it is `error`: the connection was lost, or voice is full. */
  error: "lost" | "full" | null;
  mode: "talk" | "listening-only";
  muted: boolean;
  /** This browser's seat, once the server has welcomed it. */
  you: string | null;
  peers: Record<string, VoicePeer>;
  join(): Promise<void>;
  leave(): void;
  setMuted(muted: boolean): void;
}

export const VoiceContext = createContext<VoiceState | null>(null);

/** The play screen's voice, or null outside a `VoiceProvider`. */
export function useVoiceState(): VoiceState | null {
  return useContext(VoiceContext);
}

export const RECONNECT_MS = [1000, 2000, 5000];
export const PING_MS = 20_000;
/** A peer's ring goes out this long after its last speaking frame. */
export const SPEAKING_FADE_MS = 300;
/** Audio waiting in the socket past this is dropped rather than queued: late speech is worse than a gap. */
const BACKLOG_BYTES = 16 * 1024;

type Message =
  | { type: "welcome"; you: string; slot: number; talk: boolean; peers: ({ seat_id: string } & Omit<VoicePeer, "speaking">)[] }
  | ({ type: "peer"; seat_id: string } & Omit<VoicePeer, "speaking">)
  | { type: "left"; seat_id: string; slot: number }
  | { type: "bye"; reason: "off" | "left-table" | "replaced" | "full" }
  | { type: "pong" };

export function voiceUrl(campaignId: string): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/campaigns/${encodeURIComponent(campaignId)}/voice`;
}

interface Live {
  socket: WebSocket | null;
  context: AudioContext | null;
  mic: Microphone | null;
  player: Player | null;
  ping: ReturnType<typeof setInterval> | null;
  retry: ReturnType<typeof setTimeout> | null;
  tries: number;
  /** Set when this side ends it: no reconnect. */
  ending: boolean;
  fades: Map<string, ReturnType<typeof setTimeout>>;
  listeningOnly: boolean;
  muted: boolean;
}

export function useVoice({ campaignId, allowed, role }: { campaignId: string; allowed: boolean; role: SeatRole }): VoiceState {
  const [support, setSupport] = useState<VoiceSupport | null>(null);
  const [status, setStatus] = useState<VoiceStatus>("off");
  const [error, setError] = useState<VoiceState["error"]>(null);
  const [mode, setMode] = useState<VoiceState["mode"]>("talk");
  const [muted, setMutedState] = useState(false);
  const [you, setYou] = useState<string | null>(null);
  const [peers, setPeers] = useState<Record<string, VoicePeer>>({});
  const [switchedOff, setSwitchedOff] = useState(false);
  const live = useRef<Live>({
    socket: null,
    context: null,
    mic: null,
    player: null,
    ping: null,
    retry: null,
    tries: 0,
    ending: false,
    fades: new Map(),
    listeningOnly: false,
    muted: false,
  });

  useEffect(() => {
    let current = true;
    void voiceSupport().then((found) => current && setSupport(found));
    return () => {
      current = false;
    };
  }, []);

  // A new answer from the server about the campaign's voice replaces what a `bye` said.
  useEffect(() => setSwitchedOff(false), [allowed]);

  const stopAll = useCallback(() => {
    const l = live.current;
    l.ending = true;
    if (l.retry) clearTimeout(l.retry);
    if (l.ping) clearInterval(l.ping);
    l.retry = l.ping = null;
    for (const fade of l.fades.values()) clearTimeout(fade);
    l.fades.clear();
    const socket = l.socket;
    l.socket = null;
    if (socket && socket.readyState <= WebSocket.OPEN) socket.close(1000);
    l.mic?.stop();
    l.player?.stop();
    void l.context?.close().catch(() => {});
    l.mic = l.player = l.context = null;
    setPeers({});
    setYou(null);
  }, []);

  const sendState = useCallback(() => {
    const l = live.current;
    if (l.socket?.readyState === WebSocket.OPEN)
      l.socket.send(JSON.stringify({ type: "state", muted: l.muted, listening_only: l.listeningOnly }));
  }, []);

  const speaking = useCallback((seatId: string, on: boolean) => {
    const l = live.current;
    const fade = l.fades.get(seatId);
    if (fade) clearTimeout(fade);
    if (on) l.fades.set(seatId, setTimeout(() => speaking(seatId, false), SPEAKING_FADE_MS));
    else l.fades.delete(seatId);
    setPeers((all) => (all[seatId] && all[seatId].speaking !== on ? { ...all, [seatId]: { ...all[seatId], speaking: on } } : all));
  }, []);

  const connect = useCallback(() => {
    const l = live.current;
    const socket = new WebSocket(voiceUrl(campaignId));
    socket.binaryType = "arraybuffer";
    l.socket = socket;
    const slots = new Map<number, string>();
    socket.onopen = () => sendState();
    socket.onmessage = (event: MessageEvent<string | ArrayBuffer>) => {
      if (l.socket !== socket) return;
      if (typeof event.data !== "string") {
        let frame;
        try {
          frame = decodeRelayed(event.data);
        } catch {
          return;
        }
        l.player?.push(frame);
        const seatId = slots.get(frame.slot);
        if (seatId && frame.speaking) speaking(seatId, true);
        return;
      }
      const message = JSON.parse(event.data) as Message;
      if (message.type === "welcome") {
        l.tries = 0;
        slots.clear();
        const known: Record<string, VoicePeer> = {};
        for (const { seat_id, ...peer } of message.peers) {
          known[seat_id] = { ...peer, speaking: false };
          slots.set(peer.slot, seat_id);
        }
        setPeers(known);
        setYou(message.you);
        setError(null);
        setStatus("in");
        if (l.ping) clearInterval(l.ping);
        l.ping = setInterval(() => socket.readyState === WebSocket.OPEN && socket.send('{"type":"ping"}'), PING_MS);
      } else if (message.type === "peer") {
        const { type: _, seat_id, ...peer } = message;
        slots.set(peer.slot, seat_id);
        setPeers((all) => ({ ...all, [seat_id]: { ...peer, speaking: all[seat_id]?.speaking ?? false } }));
      } else if (message.type === "left") {
        slots.delete(message.slot);
        l.player?.forget(message.slot);
        setPeers((all) => {
          const { [message.seat_id]: _, ...rest } = all;
          return rest;
        });
      } else if (message.type === "bye") {
        if (message.reason === "off") setSwitchedOff(true);
        if (message.reason === "full") setError("full");
        l.ending = true;
      }
    };
    socket.onclose = (event) => {
      if (l.socket !== socket) return;
      l.socket = null;
      if (l.ping) clearInterval(l.ping);
      l.ping = null;
      // The server's 4000 (off), 4001 (left the table), 4009 (replaced) and 4029 (full) end it, as Leave does.
      const ended = l.ending || [4000, 4001, 4009, 4029].includes(event.code);
      if (!ended && l.tries < RECONNECT_MS.length) {
        setStatus("joining");
        l.retry = setTimeout(connect, RECONNECT_MS[l.tries++]);
        return;
      }
      const full = event.code === 4029;
      stopAll();
      if (ended && !full) {
        setStatus("off");
      } else {
        setError(full ? "full" : "lost");
        setStatus("error");
      }
    };
  }, [campaignId, sendState, speaking, stopAll]);

  const join = useCallback(async () => {
    const l = live.current;
    if (l.socket || status === "joining") return;
    stopAll();
    l.ending = false;
    l.tries = 0;
    setError(null);
    setStatus("joining");
    // Leave, or the play screen going, while the browser is asked (the microphone prompt can wait on the player for
    // long) ends it: what was just obtained is let go at once rather than kept by no one.
    const left = () => {
      if (l.ending) stopAll();
      return l.ending;
    };
    try {
      l.context = await openAudio();
      if (left()) return;
      l.player = await startPlayer(l.context);
      if (left()) return;
    } catch {
      stopAll();
      setError("lost");
      setStatus("error");
      return;
    }
    l.listeningOnly = true;
    if (role !== "observer" && support === "talk") {
      try {
        l.mic = await startMicrophone(l.context, (frame) => {
          const socket = l.socket;
          if (socket?.readyState === WebSocket.OPEN && socket.bufferedAmount < BACKLOG_BYTES) socket.send(frame);
        });
        l.listeningOnly = false;
      } catch {
        // Refused or missing: listening only.
      }
      if (left()) return;
    }
    l.mic?.setMuted(l.muted);
    setMode(l.listeningOnly ? "listening-only" : "talk");
    connect();
  }, [connect, role, status, stopAll, support]);

  const leave = useCallback(() => {
    stopAll();
    setError(null);
    setStatus("off");
  }, [stopAll]);

  const setMuted = useCallback(
    (m: boolean) => {
      const l = live.current;
      l.muted = m;
      l.mic?.setMuted(m);
      setMutedState(m);
      sendState();
    },
    [sendState],
  );

  const permitted = allowed && !switchedOff;
  // Voice switched off, the campaign changed, or the play screen went: leave.
  useEffect(() => {
    if (!permitted) leave();
  }, [permitted, leave]);
  useEffect(() => () => stopAll(), [campaignId, stopAll]);

  return { allowed: permitted, support, status, error, mode, muted, you, peers, join, leave, setMuted };
}
