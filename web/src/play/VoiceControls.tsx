import { useSystemAlert } from "../components/alerts";
import { useT } from "../i18n";
import { usePhone } from "./usePhone";
import { useVoiceState } from "./voice/useVoice";
import styles from "./voice/voice.module.css";

/**
 * Join voice, Leave voice and Mute (table voice and fixes Task V2.2), in the play header on a desktop and on the Table
 * screen on a phone, over the `VoiceProvider`'s connection. Nothing while the campaign's voice is off; a note instead
 * of the button where this browser can't (no decoder, or not a secure page), as a system alert one may dismiss;
 * "listening only" for a seat that hears
 * but doesn't talk.
 */
export default function VoiceControls() {
  const t = useT();
  const voice = useVoiceState();
  const phone = usePhone();
  const unsupported = Boolean(voice?.allowed) && voice?.support === "none";
  useSystemAlert(unsupported ? { id: "voice-unsupported", tone: "warning", text: t("voice.unsupported") } : null);
  if (!voice || !voice.allowed || voice.support === null || voice.support === "none") return null;
  return (
    <div className={phone ? `${styles.controls} ${styles.stacked}` : styles.controls} data-testid="voice-controls" data-status={voice.status} role="group" aria-label={t("voice.label")}>
      {voice.status === "in" ? (
        <>
          <button type="button" data-testid="voice-leave" onClick={voice.leave}>
            {t("voice.leave")}
          </button>
          {voice.mode === "talk" ? (
            <button type="button" data-testid="voice-mute" aria-pressed={voice.muted} onClick={() => voice.setMuted(!voice.muted)}>
              {t(voice.muted ? "voice.unmute" : "voice.mute")}
            </button>
          ) : (
            <span className={styles.note} data-testid="voice-listening-only">
              {t("voice.listeningOnly")}
            </span>
          )}
        </>
      ) : voice.status === "error" ? (
        <>
          <span role="alert" className={styles.note}>
            {t(voice.error === "full" ? "voice.full" : "voice.lost")}
          </span>
          <button type="button" data-testid="voice-join" onClick={() => void voice.join()}>
            {t("voice.joinAgain")}
          </button>
        </>
      ) : (
        <button type="button" data-testid="voice-join" disabled={voice.status === "joining"} onClick={() => void voice.join()}>
          {t(voice.status === "joining" ? "voice.joining" : "voice.join")}
        </button>
      )}
    </div>
  );
}
