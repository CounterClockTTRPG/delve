import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import SeatIndicators from "./SeatIndicators";
import { hostSeat, seat } from "./testing";
import VoiceControls from "./VoiceControls";
import { encodeFrame } from "./voice/framing";
import VoiceProvider from "./voice/VoiceProvider";
import { FakeWebSocket, fakeContext, stubVoiceBrowser, unstubVoiceBrowser } from "./voice/testing";
import { SPEAKING_FADE_MS } from "./voice/useVoice";

vi.mock("./voice/audio", () => ({ openAudio: vi.fn(async () => fakeContext()) }));
vi.mock("./voice/player", () => ({
  startPlayer: vi.fn(async () => ({ push: vi.fn(), forget: vi.fn(), stop: vi.fn() })),
}));

const ana = seat("seat_00000000000a", "Ana", { language: "nl", characters: ["chr_00000000000a"] });
const bo = seat("seat_00000000000b", "Bo", { characters: ["chr_00000000000b"] });
const cy = seat("seat_00000000000c", "Cy", { role: "observer" });

describe("SeatIndicators", () => {
  it("shows each acting seat as idle, typing or submitted, and leaves observers out", () => {
    render(
      <I18nProvider language="en">
        <SeatIndicators
          seats={[hostSeat, ana, bo, cy]}
          typing={{ [ana.id]: "typing", [bo.id]: "typing" }}
          submitted={[bo.id]}
          mySeatId={hostSeat.id}
        />
      </I18nProvider>,
    );
    const shown = screen.getByTestId("seat-indicators");
    const state = (id: string) => shown.querySelector(`[data-seat="${id}"]`)?.getAttribute("data-state");
    expect(state(hostSeat.id)).toBe("idle");
    expect(state(ana.id)).toBe("typing");
    expect(state(bo.id), "submitted wins over typing").toBe("submitted");
    expect(state(cy.id)).toBeUndefined();
    expect(shown.textContent).toContain("Ana");
    expect(shown.textContent).toContain("You");
    expect(shown.querySelector(`[data-seat="${bo.id}"]`)?.textContent).toContain("Submitted");
  });

  it("says nothing for a seat that hasn't acted yet, but to a screen reader (DEL-260)", () => {
    render(
      <I18nProvider language="en">
        <SeatIndicators seats={[hostSeat, ana]} typing={{ [ana.id]: "typing" }} submitted={[]} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    const shown = screen.getByTestId("seat-indicators");
    const idle = shown.querySelector(`[data-seat="${hostSeat.id}"] .seat-state`)!;
    expect(idle.textContent).toBe("Not acted yet");
    expect(idle.classList.contains("visually-hidden")).toBe(true);
    expect(shown.querySelector(`[data-seat="${ana.id}"] .seat-state`)!.classList.contains("visually-hidden")).toBe(false);
  });

  it("marks a seat that isn't there", () => {
    render(
      <I18nProvider language="en">
        <SeatIndicators seats={[hostSeat, { ...ana, present: false }]} typing={{}} submitted={[]} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    expect(screen.getByTestId("seat-indicators").querySelector(`[data-seat="${ana.id}"]`)?.textContent).toContain("Away");
  });

  it("avatars beside the names", () => {
    const profile = { account_id: "acc_00000000000a", display_name: "Ana", pronouns: "", avatar: { picture: "0123456789ab" }, colour: "gold" };
    render(
      <I18nProvider language="en">
        <SeatIndicators seats={[hostSeat, { ...ana, profile }]} typing={{}} submitted={[]} mySeatId={hostSeat.id} />
      </I18nProvider>,
    );
    const shown = screen.getByTestId("seat-indicators");
    const face = shown.querySelector(`[data-seat="${ana.id}"] .avatar img`);
    expect(face?.getAttribute("src")).toBe("/api/profiles/acc_00000000000a/avatar?v=0123456789ab");
    expect(shown.querySelector(`[data-seat="${hostSeat.id}"] .avatar-none`)).not.toBeNull();
  });
});

describe("SeatIndicators in voice", () => {
  afterEach(() => {
    vi.useRealTimers();
    unstubVoiceBrowser();
  });

  /** The host's play screen, in voice with Ana (slot 1, talking) and Bo (slot 2, listening only). */
  async function inVoice() {
    stubVoiceBrowser();
    render(
      <I18nProvider language="en">
        <VoiceProvider campaignId="cmp_00000000000a" allowed role="host">
          <VoiceControls />
          <SeatIndicators seats={[hostSeat, ana, bo, cy]} typing={{}} submitted={[]} mySeatId={hostSeat.id} />
        </VoiceProvider>
      </I18nProvider>,
    );
    const shown = screen.getByTestId("seat-indicators");
    expect(shown.querySelector('[data-testid="voice-mark"]'), "nobody is in voice before Join").toBeNull();
    fireEvent.click(await screen.findByTestId("voice-join"));
    await waitFor(() => expect(FakeWebSocket.open).toHaveLength(1));
    const socket = FakeWebSocket.open[0];
    const peer = { talk: true, muted: false, listening_only: false };
    socket.accept({
      you: hostSeat.id,
      peers: [
        { seat_id: ana.id, name: "Ana", slot: 1, ...peer },
        { seat_id: bo.id, name: "Bo", slot: 2, ...peer, listening_only: true },
      ],
    });
    const of = (id: string, part: string) => shown.querySelector(`[data-seat="${id}"] [data-testid="${part}"]`);
    await waitFor(() => expect(of(ana.id, "voice-mark")).not.toBeNull());
    return { socket, of };
  }

  it("marks who is in voice, muted or listening only", async () => {
    const { socket, of } = await inVoice();
    expect(of(hostSeat.id, "voice-mark")?.getAttribute("data-voice")).toBe("talk");
    expect(of(ana.id, "voice-mark")?.textContent).toBe("In voice");
    expect(of(bo.id, "voice-mark")?.textContent).toBe("Listening only");
    socket.receive({ type: "peer", seat_id: ana.id, name: "Ana", slot: 1, talk: true, muted: true, listening_only: false });
    expect(of(ana.id, "voice-mark")?.textContent).toBe("Muted");
    socket.receive({ type: "left", seat_id: ana.id, slot: 1 });
    expect(of(ana.id, "voice-mark")).toBeNull();
  });

  it("lights the speaking mark while the frames say speaking", async () => {
    const { socket, of } = await inVoice();
    const ring = () => of(ana.id, "voice-mark")?.getAttribute("data-speaking");
    expect(ring()).toBe("false");
    const relayed = (slot: number, speaking: boolean) => {
      const frame = new Uint8Array(encodeFrame({ speaking, seq: 1, tsMs: 20, payload: new Uint8Array([1, 2, 3]) }));
      const out = new Uint8Array(frame.length + 1);
      out[0] = slot;
      out.set(frame, 1);
      return out.buffer;
    };
    vi.useFakeTimers();
    socket.receive(relayed(1, false));
    expect(ring()).toBe("false");
    socket.receive(relayed(1, true));
    expect(ring()).toBe("true");
    expect(of(ana.id, "voice-mark")?.getAttribute("aria-label")).toBe("In voice, Speaking");
    expect(of(bo.id, "voice-mark")?.getAttribute("data-speaking")).toBe("false");
    await act(async () => vi.advanceTimersByTime(SPEAKING_FADE_MS + 10));
    expect(ring()).toBe("false");
  });
});
