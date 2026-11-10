import { useState, type ReactNode } from "react";
import { useLanguage, useT } from "../i18n";
import { shortWhen } from "../play/Story";
import { MESSAGE_CHARS, type JoinRequest } from "./api";

/**
 * A request to join's thread (DEL-204): the player's note and the messages between the player and the hosts, oldest
 * first, each under its writer's name, then, while the request waits, a box to answer in. `actions` go beside Send
 * (Withdraw for the player; Accept and Decline for a host). A decided request shows its thread alone.
 */
export default function RequestThread({
  request,
  onSend,
  sending = false,
  actions = null,
}: {
  request: JoinRequest;
  onSend: (text: string) => void;
  sending?: boolean;
  actions?: ReactNode;
}) {
  const t = useT();
  const language = useLanguage();
  const [text, setText] = useState("");
  const words = text.trim();
  const pending = request.status === "pending";
  return (
    <div className="request-thread" data-testid={`request-${request.id}`}>
      {request.messages.length === 0 ? (
        <p className="placeholder">{t("requests.noNote")}</p>
      ) : (
        <ol className="request-messages">
          {request.messages.map((message, index) => (
            <li key={index} className={message.from === "host" ? "from-host" : "from-player"}>
              <span className="request-who">{message.name}</span>{" "}
              <time className="row-meta" dateTime={message.at}>
                {shortWhen(message.at, language)}
              </time>
              <p>{message.text}</p>
            </li>
          ))}
        </ol>
      )}
      {pending && (
        <form
          className="request-reply"
          onSubmit={(e) => {
            e.preventDefault();
            if (!words || sending) return;
            onSend(words);
            setText("");
          }}
        >
          <label className="visually-hidden" htmlFor={`reply-${request.id}`}>
            {t("requests.reply")}
          </label>
          <textarea
            id={`reply-${request.id}`}
            rows={2}
            maxLength={MESSAGE_CHARS}
            value={text}
            placeholder={t("requests.replyPlaceholder")}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="request-actions">
            <button type="submit" disabled={!words || sending}>
              {t("requests.send")}
            </button>
            {actions}
          </div>
        </form>
      )}
    </div>
  );
}
