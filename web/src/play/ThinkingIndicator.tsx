import { useEffect, useState } from "react";
import { useT } from "../i18n";
import DidYouKnow from "./DidYouKnow";
import { useDidYouKnow } from "./didYouKnowSetting";

/** After this long, the indicator says gently that this beat is a big one. */
export const BIG_ONE_S = 30;

function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * The DM is answering: the time since the beat closed, and for the host and co-hosts the tool calls so far
 * (`toolCount`, left out for anyone else: plan 7 Task 18). `elapsedS` is the server's count when the beat was last
 * read; the clock runs on from there. With the campaign, a fact of its setting shows below
 * ("Did you know"), unless this browser turned it off in Preferences; never on a phone.
 */
export default function ThinkingIndicator({
  elapsedS,
  toolCount,
  campaignId,
}: {
  elapsedS: number;
  toolCount?: number;
  campaignId?: string;
}) {
  const t = useT();
  const [showFacts] = useDidYouKnow();
  const [since] = useState(() => Date.now() - elapsedS * 1000);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const seconds = (now - since) / 1000;
  return (
    <div className="thinking-wrap">
      <p className="thinking" data-testid="thinking" role="status">
        <span className="thinking-dots" aria-hidden="true" />
        <span>{t("play.thinking")}</span>
        <span className="thinking-meta">
          {toolCount === undefined
            ? clock(seconds)
            : t("play.thinkingMeta", {
                time: clock(seconds),
                tools: t(toolCount === 1 ? "play.toolCallOne" : "play.toolCalls", { count: String(toolCount) }),
              })}
        </span>
        {seconds >= BIG_ONE_S && <span className="thinking-big">{t("play.bigOne")}</span>}
      </p>
      {campaignId && showFacts && <DidYouKnow campaignId={campaignId} />}
    </div>
  );
}
