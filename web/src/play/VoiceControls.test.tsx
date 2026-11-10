import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AlertsProvider, SystemAlerts } from "../components/alerts";
import { I18nProvider } from "../i18n";
import Play from "../routes/Play";
import { FakeEventSource, hostSeat, playRoutes, playState, renderWith, seat, stubFetch } from "./testing";
import VoiceControls from "./VoiceControls";
import VoiceProvider from "./voice/VoiceProvider";
import { openAudio } from "./voice/audio";
import { FakeWebSocket, fakeContext, stubVoiceBrowser, unstubVoiceBrowser } from "./voice/testing";

vi.mock("qrcode", () => ({ default: { toCanvas: vi.fn(async () => undefined) } }));
vi.mock("./voice/audio", () => ({ openAudio: vi.fn(async () => fakeContext()) }));
vi.mock("./voice/player", () => ({
  startPlayer: vi.fn(async () => ({ push: vi.fn(), forget: vi.fn(), stop: vi.fn() })),
}));

afterEach(() => unstubVoiceBrowser());

function renderControls(props: { allowed?: boolean; role?: "host" | "player" | "observer" } = {}) {
  const ui = (allowed: boolean) => (
    <I18nProvider language="en">
      <AlertsProvider>
        <SystemAlerts />
        <VoiceProvider campaignId="cmp_00000000000a" allowed={allowed} role={props.role ?? "player"}>
          <VoiceControls />
        </VoiceProvider>
      </AlertsProvider>
    </I18nProvider>
  );
  const rendered = render(ui(props.allowed ?? true));
  return { ...rendered, allow: (allowed: boolean) => rendered.rerender(ui(allowed)) };
}

async function joined() {
  fireEvent.click(await screen.findByTestId("voice-join"));
  await waitFor(() => expect(FakeWebSocket.open).toHaveLength(1));
  const socket = FakeWebSocket.open[0];
  socket.accept();
  await screen.findByTestId("voice-leave");
  return socket;
}

describe("VoiceControls", () => {
  it("asks for no microphone before Join", async () => {
    const mic = stubVoiceBrowser();
    renderControls();
    expect(await screen.findByTestId("voice-join")).toBeTruthy();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
    expect(FakeWebSocket.open).toHaveLength(0);
    await joined();
    expect(mic.getUserMedia).toHaveBeenCalledOnce();
    expect(FakeWebSocket.open[0].url).toBe(`ws://${location.host}/api/campaigns/cmp_00000000000a/voice`);
  });

  it("joins listening only when the microphone is refused", async () => {
    stubVoiceBrowser({ refuse: true });
    renderControls();
    const socket = await joined();
    expect(screen.getByTestId("voice-listening-only").textContent).toBe("Listening only");
    expect(screen.queryByTestId("voice-mute")).toBeNull();
    expect(socket.messages()).toContainEqual({ type: "state", muted: false, listening_only: true });
  });

  it("an observer and a browser with no encoder listen without asking for the microphone", async () => {
    const mic = stubVoiceBrowser();
    renderControls({ role: "observer" });
    await joined();
    expect(screen.getByTestId("voice-listening-only")).toBeTruthy();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
  });

  it("Mute turns the track off and tells the others", async () => {
    const mic = stubVoiceBrowser();
    renderControls();
    const socket = await joined();
    expect(socket.messages()).toContainEqual({ type: "state", muted: false, listening_only: false });
    fireEvent.click(screen.getByTestId("voice-mute"));
    expect(mic.track.enabled).toBe(false);
    expect(socket.messages()).toContainEqual({ type: "state", muted: true, listening_only: false });
    expect(screen.getByTestId("voice-mute").textContent).toBe("Unmute");
    fireEvent.click(screen.getByTestId("voice-mute"));
    expect(mic.track.enabled).toBe(true);
  });

  it("Leave closes the socket and the microphone", async () => {
    const mic = stubVoiceBrowser();
    renderControls();
    await joined();
    fireEvent.click(screen.getByTestId("voice-leave"));
    expect(FakeWebSocket.open).toHaveLength(0);
    expect(mic.track.stop).toHaveBeenCalled();
    expect(await screen.findByTestId("voice-join")).toBeTruthy();
  });

  it("lets go of the microphone and the audio when the play screen goes while the browser asks for the microphone", async () => {
    const mic = stubVoiceBrowser();
    const context = fakeContext();
    const close = vi.spyOn(context, "close");
    vi.mocked(openAudio).mockResolvedValueOnce(context);
    let grant: (stream: unknown) => void = () => {};
    const asked = new Promise((resolve) => (grant = resolve));
    mic.getUserMedia.mockImplementationOnce(() => asked);
    const { unmount } = renderControls();
    fireEvent.click(await screen.findByTestId("voice-join"));
    await waitFor(() => expect(mic.getUserMedia).toHaveBeenCalledOnce());
    unmount();
    expect(close).toHaveBeenCalledOnce();
    // The prompt is answered after the screen went: the microphone is stopped, and no socket opened.
    await act(async () => grant({ getAudioTracks: () => [mic.track], getTracks: () => [mic.track] }));
    await waitFor(() => expect(mic.track.stop).toHaveBeenCalled());
    expect(close).toHaveBeenCalledOnce();
    expect(FakeWebSocket.open).toHaveLength(0);
  });

  it("hides the button while the campaign's voice is off, and when the host switches it off", async () => {
    stubVoiceBrowser();
    const { allow } = renderControls({ allowed: false });
    await act(async () => {});
    expect(screen.queryByTestId("voice-controls")).toBeNull();
    allow(true);
    const socket = await joined();
    socket.receive({ type: "bye", reason: "off" });
    socket.serverClose(4000);
    await waitFor(() => expect(screen.queryByTestId("voice-controls")).toBeNull());
  });

  it("tries a dropped socket again, then says voice was lost", async () => {
    stubVoiceBrowser();
    renderControls();
    const socket = await joined();
    vi.useFakeTimers();
    try {
      socket.serverClose(1006);
      for (const wait of [1000, 2000, 5000]) {
        await vi.advanceTimersByTimeAsync(wait);
        expect(FakeWebSocket.open).toHaveLength(1);
        FakeWebSocket.open[0].serverClose(1006);
      }
    } finally {
      vi.useRealTimers();
    }
    expect((await screen.findByRole("alert")).textContent).toBe("Voice was lost.");
    expect(screen.getByTestId("voice-join").textContent).toBe("Join voice again");
  });

  it("says why where the browser can't, as a system alert this browser can dismiss", async () => {
    localStorage.clear();
    stubVoiceBrowser();
    vi.stubGlobal("AudioWorkletNode", undefined);
    const { unmount } = renderControls();
    const alert = await screen.findByTestId("voice-unsupported");
    expect(alert.textContent).toContain("can't join voice");
    expect(alert.getAttribute("role")).toBe("alert");
    expect(screen.queryByTestId("voice-join")).toBeNull();
    fireEvent.click(within(alert).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("voice-unsupported")).toBeNull();

    // Dismissed stays dismissed on the next page.
    unmount();
    renderControls();
    await waitFor(() => expect(screen.queryByTestId("voice-controls")).toBeNull());
    expect(screen.queryByTestId("voice-unsupported")).toBeNull();
    localStorage.clear();
  });
});

describe("voice on the play screen", () => {
  beforeEach(() => {
    FakeEventSource.open = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("puts the controls on a phone's Table screen (390 px)", async () => {
    stubVoiceBrowser();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    const ana = seat("seat_00000000000a", "Ana", { characters: ["chr_00000000000a"] });
    stubFetch(playRoutes(playState({ voice: "allowed" }), [], { seats: [hostSeat, ana] }));
    renderWith(<Play />);
    const tabs = await screen.findByTestId("phone-tabs");
    expect(screen.queryByTestId("voice-join")).toBeNull();
    fireEvent.click(within(tabs).getByRole("button", { name: "Table" }));
    expect(await within(screen.getByTestId("phone-screen")).findByTestId("voice-join")).toBeTruthy();
  });
});
