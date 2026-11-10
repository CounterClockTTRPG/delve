import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { useLocation } from "react-router-dom";
import { useLanguage, useT } from "../i18n";
import { Related, TopicBody } from "./HelpPages";
import { inLanguage, topic, topicsFor, useTopicLanguage, type Audience } from "./topics";
import { useTours } from "./tour";
import "./help.css";

// The app's help (DEL-145): a panel at the side with the help topics about the screen you are on, for your role (a
// player's own; an organiser's and the player's; every topic for the owner). A topic opens in the panel; "All help"
// opens the help pages. Its button is Help in the nav, or a "?" in the corner for a seat, which has no nav. Every
// screen offers the basics of roleplaying (DEL-285), and a topic read here leads on to the next, here too.

/** The first of the newcomers' topics (DEL-282). */
const START = "what-is-a-roleplaying-game";

const HELP_ICON = "M12 3a9 9 0 100 18 9 9 0 000-18zM9.5 9.5a2.5 2.5 0 114 2c-1 .6-1.5 1.2-1.5 2.2M12 17h.01";

export function HelpPanel({ role, place }: { role: Audience; place: "nav" | "corner" }) {
  const t = useT();
  const language = useLanguage();
  const topicLanguage = useTopicLanguage();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [reading, setReading] = useState<string | null>(null);
  const here = topicsFor(pathname, role);
  const tours = useTours();
  const found = reading ? topic(reading) : undefined;
  const shown = found && inLanguage(found, topicLanguage);
  const start = topic(START);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setReading(null);
      }}
    >
      <Dialog.Trigger asChild>
        {place === "nav" ? (
          <button type="button" className="nav-help" data-testid="nav-help" data-tour="help">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d={HELP_ICON} />
            </svg>
            <span>{t("landing.help")}</span>
          </button>
        ) : (
          <button type="button" className="help-button" data-tour="help" aria-label={t("landing.help")}>
            ?
          </button>
        )}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="help-panel-overlay" />
        <Dialog.Content className="help-panel" aria-describedby={undefined}>
          <div className="help-panel-head">
            <Dialog.Title className="help-panel-title">{t("landing.help")}</Dialog.Title>
            <Dialog.Close className="help-panel-close" aria-label={t("help.close")}>
              ×
            </Dialog.Close>
          </div>
          {shown ? (
            <>
              <button type="button" className="help-panel-back" onClick={() => setReading(null)}>
                {t("help.back")}
              </button>
              <TopicBody topic={shown} heading={2} />
              <Related topic={shown} onOpen={setReading} />
              <p>
                <a href={`/help/${shown.slug}?lang=${language}`} target="_blank" rel="noreferrer">
                  {t("help.ownPage")}
                </a>
              </p>
            </>
          ) : (
            <>
              {here.length > 0 ? (
                <ul className="help-topic-list" aria-label={t("help.aboutThisScreen")}>
                  {here
                    .map((each) => inLanguage(each, topicLanguage))
                    .map((each) => (
                      <li key={each.slug}>
                        <button type="button" onClick={() => setReading(each.slug)}>
                          {each.title}
                        </button>
                        {each.summary && <span>{each.summary}</span>}
                      </li>
                    ))}
                </ul>
              ) : (
                <p>{t("help.noneHere")}</p>
              )}
              {start && !here.some((each) => each.slug === START) && (
                <p>
                  {t("help.newcomer")}{" "}
                  <button type="button" className="help-panel-back" onClick={() => setReading(START)}>
                    {t("help.newcomer.start")}
                  </button>
                </p>
              )}
              {tours?.here.map((tour) => (
                <p key={tour.id}>
                  <button
                    type="button"
                    className="help-panel-back"
                    onClick={() => {
                      setOpen(false);
                      tours.start(tour.id);
                    }}
                  >
                    {t("help.takeTour", { tour: t(tour.title) })}
                  </button>
                </p>
              ))}
              <p>
                <a href={`/help?lang=${language}`} target="_blank" rel="noreferrer">
                  {t("help.all")}
                </a>
              </p>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
