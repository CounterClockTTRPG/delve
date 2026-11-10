import { Timer } from "lucide-react";
import { useEffect, useState } from "react";
import { useT } from "../i18n";

function left(deadline: string): number {
  return Math.max(0, Math.ceil((Date.parse(deadline) - Date.now()) / 1000));
}

/** The beat timer: the time left to the open beat's deadline, the same for everyone (spec §7.1). Nothing without
 * a timer. */
export default function BeatTimer({ deadline }: { deadline: string | null | undefined }) {
  const t = useT();
  const [seconds, setSeconds] = useState(() => (deadline ? left(deadline) : 0));

  useEffect(() => {
    if (!deadline) return;
    setSeconds(left(deadline));
    const tick = setInterval(() => setSeconds(left(deadline)), 1000);
    return () => clearInterval(tick);
  }, [deadline]);

  if (!deadline) return null;
  const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <p className={seconds <= 10 ? "beat-timer ending" : "beat-timer"} data-testid="beat-timer" role="timer">
      <Timer size={14} aria-hidden="true" /> {t("play.timeLeft", { time })}
    </p>
  );
}
