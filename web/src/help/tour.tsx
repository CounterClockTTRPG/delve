import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState } from "react";
import { matchPath, useLocation } from "react-router-dom";
import { useT, type MessageKey } from "../i18n";
import { audiencesOf, type Audience } from "./topics";
import "./help.css";

// The guided tours (DEL-213): a few steps over a screen, each lighting up one part of it (an element with that
// `data-tour`, or a selector) with a card saying what it is for: Back, Next and Skip. A browser is offered one tour,
// the first time a screen with a tour opens with its first part on it; once the reader has answered it (Show me or Not
// now), no other screen offers one (DEL-267: every screen asked again), and Skip the tours offers none at all
// (DEL-211). The help panel plays any tour again. Steps whose part
// isn't on the screen (a player's Preferences have no Backends) are left out. Their words are keys of the
// dictionaries (DEL-284), in the reader's language.

export interface TourStep {
  /** A `data-tour` name, or a CSS selector when it starts with `#` or `[`. */
  target: string;
  title: MessageKey;
  text: MessageKey;
}

export interface Tour {
  id: string;
  title: MessageKey;
  /** Router paths the tour is about. */
  screens: string[];
  /** The least role it is for: `player` for anyone, `organiser` for organisers and the owner. */
  audience: Audience;
  steps: TourStep[];
}

export const TOURS: Tour[] = [
  {
    id: "play",
    title: "tour.play.title",
    screens: ["/play/:campaignId"],
    audience: "player",
    steps: [
      {
        target: "play-head",
        title: "tour.play.1.title",
        text: "tour.play.1.text",
      },
      {
        target: "story",
        title: "tour.play.2.title",
        text: "tour.play.2.text",
      },
      {
        target: "composer",
        title: "tour.play.3.title",
        text: "tour.play.3.text",
      },
      {
        target: "party",
        title: "tour.play.4.title",
        text: "tour.play.4.text",
      },
      {
        target: "world",
        title: "tour.play.5.title",
        text: "tour.play.5.text",
      },
      {
        target: "talk",
        title: "tour.play.6.title",
        text: "tour.play.6.text",
      },
      {
        target: "play-tabs",
        title: "tour.play.7.title",
        text: "tour.play.7.text",
      },
      {
        target: "help",
        title: "tour.play.8.title",
        text: "tour.play.8.text",
      },
    ],
  },
  {
    id: "new-campaign",
    title: "tour.new-campaign.title",
    screens: ["/campaigns"],
    audience: "organiser",
    steps: [
      {
        target: "new-campaign",
        title: "tour.new-campaign.1.title",
        text: "tour.new-campaign.1.text",
      },
      {
        target: "help",
        title: "tour.new-campaign.2.title",
        text: "tour.new-campaign.2.text",
      },
    ],
  },
  {
    id: "campaign",
    title: "tour.campaign.title",
    screens: ["/campaigns/:id"],
    audience: "organiser",
    steps: [
      {
        target: "campaign-tabs",
        title: "tour.campaign.1.title",
        text: "tour.campaign.1.text",
      },
      {
        target: "table-settings",
        title: "tour.campaign.2.title",
        text: "tour.campaign.2.text",
      },
      {
        target: "listing",
        title: "tour.campaign.3.title",
        text: "tour.campaign.3.text",
      },
      {
        target: "schedule",
        title: "tour.campaign.4.title",
        text: "tour.campaign.4.text",
      },
      {
        target: "house-rules",
        title: "tour.campaign.5.title",
        text: "tour.campaign.5.text",
      },
    ],
  },
  {
    id: "preferences",
    title: "tour.preferences.title",
    screens: ["/preferences"],
    audience: "player",
    steps: [
      {
        target: "#preferences-tab-profile",
        title: "tour.preferences.1.title",
        text: "tour.preferences.1.text",
      },
      {
        target: "#preferences-tab-browser",
        title: "tour.preferences.2.title",
        text: "tour.preferences.2.text",
      },
      {
        target: "#preferences-tab-backends",
        title: "tour.preferences.3.title",
        text: "tour.preferences.3.text",
      },
      {
        target: "#preferences-tab-connections",
        title: "tour.preferences.4.title",
        text: "tour.preferences.4.text",
      },
      {
        target: "#preferences-tab-storage",
        title: "tour.preferences.5.title",
        text: "tour.preferences.5.text",
      },
      {
        target: "#preferences-tab-players",
        title: "tour.preferences.6.title",
        text: "tour.preferences.6.text",
      },
    ],
  },
];

const SEEN_KEY = (id: string) => `delve.tour.${id}`;
/** Set by Skip the tours (DEL-211): this browser's reader knows Delve, and no tour is offered again. */
const SKIPPED_KEY = "delve.tours.skipped";
/** Set once the reader answered an offer (DEL-267): they know the tours are there, and Help has them. */
const ANSWERED_KEY = "delve.tours.answered";

function seen(id: string): boolean {
  try {
    return (
      localStorage.getItem(SKIPPED_KEY) !== null ||
      localStorage.getItem(ANSWERED_KEY) !== null ||
      localStorage.getItem(SEEN_KEY(id)) !== null
    );
  } catch {
    return true; // No storage: never offer, so a tour doesn't come back on every page.
  }
}

function markSeen(id: string) {
  try {
    localStorage.setItem(SEEN_KEY(id), "1");
    localStorage.setItem(ANSWERED_KEY, "1");
  } catch {
    // Without storage the tour may be offered again; nothing else depends on it.
  }
}

function skipAll() {
  try {
    localStorage.setItem(SKIPPED_KEY, "1");
  } catch {
    // As for `markSeen`.
  }
}

function find(target: string): HTMLElement | null {
  const selector = target.startsWith("#") || target.startsWith("[") ? target : `[data-tour="${target}"]`;
  for (const element of document.querySelectorAll<HTMLElement>(selector)) {
    const box = element.getBoundingClientRect();
    if (box.width > 0 && box.height > 0) return element;
  }
  return null;
}

/** The tours for the screen at `pathname`, for `role`. */
export function toursFor(pathname: string, role: Audience): Tour[] {
  const shown = audiencesOf(role);
  return TOURS.filter(
    (tour) => shown.includes(tour.audience) && tour.screens.some((path) => matchPath({ path, end: true }, pathname)),
  );
}

interface TourApi {
  /** The tours about this screen, for this reader. */
  here: Tour[];
  start: (id: string) => void;
}

const TourContext = createContext<TourApi | null>(null);

/** The tours there are here, and a way to start one; null outside a TourProvider. */
export function useTours(): TourApi | null {
  return useContext(TourContext);
}

export function TourProvider({ role, children }: { role: Audience; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const here = toursFor(pathname, role);
  const [running, setRunning] = useState<Tour | null>(null);
  const start = useCallback((id: string) => {
    const tour = TOURS.find((t) => t.id === id);
    if (!tour) return;
    markSeen(id);
    setRunning(tour);
  }, []);
  // A tour belongs to its screen: leaving the screen ends it.
  useEffect(() => setRunning(null), [pathname]);
  return (
    <TourContext.Provider value={{ here, start }}>
      {children}
      {running ? <TourRun tour={running} onEnd={() => setRunning(null)} /> : <TourOffer tours={here} onStart={start} />}
    </TourContext.Provider>
  );
}

/** The first time a screen with a tour opens in this browser, and once its first part is there: an offer of the tour. */
function TourOffer({ tours, onStart }: { tours: Tour[]; onStart: (id: string) => void }) {
  const t = useT();
  const [offered, setOffered] = useState<Tour | null>(null);
  const ids = tours.map((t) => t.id).join(",");
  useEffect(() => {
    setOffered(null);
    const unseen = tours.find((t) => !seen(t.id));
    if (!unseen) return;
    // The screen may still be loading: look for the tour's first part for a while.
    let tries = 0;
    const timer = window.setInterval(() => {
      tries += 1;
      if (unseen.steps.some((step) => find(step.target))) {
        window.clearInterval(timer);
        setOffered(unseen);
      } else if (tries > 20) window.clearInterval(timer);
    }, 500);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `ids` stands for `tours`
  }, [ids]);
  if (!offered) return null;
  const dismiss = () => {
    markSeen(offered.id);
    setOffered(null);
  };
  const skip = () => {
    skipAll();
    setOffered(null);
  };
  return (
    <section className="tour-offer" role="region" aria-label={t("tour.offer.label")} data-testid="tour-offer">
      <p>
        <strong>{t("tour.offer.new")}</strong> {t("tour.offer.text")}
      </p>
      <div className="tour-actions">
        <button type="button" className="primary" onClick={() => onStart(offered.id)}>
          {t("tour.offer.show")}
        </button>
        <button type="button" onClick={dismiss}>
          {t("tour.offer.notNow")}
        </button>
        <button type="button" className="tour-skip" data-testid="tour-skip-all" onClick={skip}>
          {t("tour.offer.skipAll")}
        </button>
      </div>
      <p className="tour-offer-hint">{t("tour.offer.hint")}</p>
    </section>
  );
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

const GAP = 10;

/** A running tour: the part of the screen lit up, and its card beside it. Escape or Skip ends it. */
function TourRun({ tour, onEnd }: { tour: Tour; onEnd: () => void }) {
  const t = useT();
  const steps = tour.steps.filter((step) => find(step.target));
  const [at, setAt] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const step = steps[at];

  useLayoutEffect(() => {
    if (!step) return;
    const element = find(step.target);
    if (!element) return;
    element.scrollIntoView({ block: "nearest", inline: "nearest" });
    const measure = () => {
      const r = element.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step]);

  useEffect(() => card.current?.focus(), [at]);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onEnd();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onEnd]);

  if (!step) return null;
  const last = at === steps.length - 1;
  // The card below the part when it fits, above it otherwise; along the window's edge for a part that fills it.
  const cardStyle: React.CSSProperties = {};
  if (box) {
    const below = box.top + box.height + GAP;
    const width = Math.min(352, window.innerWidth - 2 * GAP);
    cardStyle.left = Math.max(GAP, Math.min(box.left, window.innerWidth - width - GAP));
    cardStyle.width = width;
    if (below + 180 < window.innerHeight) cardStyle.top = below;
    else if (box.top - GAP - 180 > 0) cardStyle.bottom = window.innerHeight - box.top + GAP;
    else cardStyle.bottom = GAP;
  }
  return (
    <div className="tour" data-testid="tour">
      {box && (
        <div
          className="tour-spot"
          aria-hidden="true"
          style={{
            top: box.top - 4,
            left: box.left - 4,
            width: box.width + 8,
            height: box.height + 8,
          }}
        />
      )}
      <div
        ref={card}
        className="tour-card"
        role="dialog"
        aria-modal="false"
        aria-labelledby="tour-step-title"
        aria-describedby="tour-step-text"
        tabIndex={-1}
        style={cardStyle}
      >
        <p className="tour-count">
          {t("tour.count", {
            tour: t(tour.title),
            at: String(at + 1),
            of: String(steps.length),
          })}
        </p>
        <h2 id="tour-step-title">{t(step.title)}</h2>
        <p id="tour-step-text">{t(step.text)}</p>
        <div className="tour-actions">
          {at > 0 && (
            <button type="button" onClick={() => setAt(at - 1)}>
              {t("tour.back")}
            </button>
          )}
          <button type="button" className="primary" onClick={() => (last ? onEnd() : setAt(at + 1))}>
            {last ? t("tour.done") : t("tour.next")}
          </button>
          {!last && (
            <button type="button" className="tour-skip" onClick={onEnd}>
              {t("tour.skip")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
