import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Link, useInRouterContext } from "react-router-dom";
import { createContext, useContext, useState, type CSSProperties, type ReactNode } from "react";
import { useLanguage, useT } from "../i18n";
import Avatar from "./Avatar";
import { COLOURS, getProfile, profileKeys, type ProfileSummary } from "./api";
import { localTime } from "./localTime";
import "./profile.css";

/** Opens a player's card; null outside the table, where an avatar is a picture only. */
const OpenCard = createContext<((accountId: string) => void) | null>(null);

/**
 * The table's profile cards (players and tavern Task G3): a click on any avatar inside opens that player's card, one at
 * a time.
 */
export function ProfileCards({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <OpenCard.Provider value={setOpen}>
      {children}
      {open && <ProfileCard key={open} accountId={open} onClose={() => setOpen(null)} />}
    </OpenCard.Provider>
  );
}

/** A player's avatar at the table: a button to their card inside `ProfileCards`. */
export function TableAvatar({ profile, size = 32, name }: { profile: ProfileSummary | null | undefined; size?: number; name?: string }) {
  const open = useContext(OpenCard);
  return <Avatar profile={profile} size={size} name={name} onClick={open && profile ? () => open(profile.account_id) : undefined} />;
}

/** How a seat's talk lines show their speaker: the avatar before the name, and the colour's bar beside the line. */
export function talkFaces(seats: { id: string; name?: string; profile?: ProfileSummary | null }[], size = 24) {
  const bySeat = new Map(seats.map((s) => [s.id, s]));
  return {
    // A seat that left isn't in the list any more: its lines keep the name alone.
    face: (seatId: string | undefined) => {
      const seat = seatId ? bySeat.get(seatId) : undefined;
      return seat ? <TableAvatar profile={seat.profile} size={size} name={seat.name} /> : null;
    },
    colour: (seatId: string | undefined) => {
      const colour = seatId ? bySeat.get(seatId)?.profile?.colour : undefined;
      return colour && colour in COLOURS ? (colour as keyof typeof COLOURS) : undefined;
    },
  };
}

/** The colour's bar of a talk line, as its style. */
export const talkColourStyle = (colour: keyof typeof COLOURS | undefined) =>
  colour ? ({ "--talk-colour": COLOURS[colour] } as CSSProperties) : undefined;

/**
 * A player's profile card: their face, name and pronouns, and what they wrote about themselves; for a host of their
 * table (the server sends it only then) the note for the host and the time it is where they are. What the caller may
 * read is the server's to decide (`delve.play.profiles.card`); the card shows what came. Your own card has a way to
 * edit your profile.
 */
export default function ProfileCard({ accountId, onClose }: { accountId: string; onClose: () => void }) {
  const t = useT();
  const language = useLanguage();
  const card = useQuery({ queryKey: profileKeys.card(accountId), queryFn: () => getProfile(accountId) });
  const data = card.data;
  // Only your own card carries your language (`delve.play.profiles.card`); outside a router there is nowhere to go.
  const own = useInRouterContext() && data?.language !== undefined;
  const time = data?.time_zone ? localTime(data.time_zone, new Date(), language) : "";
  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className="dialog profile-card"
          aria-describedby={undefined}
          style={data ? ({ "--avatar-colour": COLOURS[data.colour as keyof typeof COLOURS] } as CSSProperties) : undefined}
        >
          {data ? (
            <>
              <header className="profile-card-head">
                <Avatar profile={data} size={72} />
                <div>
                  <Dialog.Title className="dialog-title">{data.display_name}</Dialog.Title>
                  {data.pronouns && (
                    <p className="profile-card-pronouns">
                      <span className="visually-hidden">{t("card.pronouns")}: </span>
                      {data.pronouns}
                    </p>
                  )}
                </div>
              </header>
              {data.about ? (
                <section aria-label={t("card.about")}>
                  <p className="profile-card-about">{data.about}</p>
                </section>
              ) : (
                <p className="placeholder">{t(own ? "card.nothingOwn" : "card.nothing")}</p>
              )}
              {data.host_note && (
                <section className="profile-card-note">
                  <h3>{t("card.note")}</h3>
                  <p>{data.host_note}</p>
                </section>
              )}
              {time && data.time_zone && (
                <p className="profile-card-time">{t("card.localTime", { time, zone: data.time_zone.replaceAll("_", " ") })}</p>
              )}
            </>
          ) : (
            <>
              <Dialog.Title className="visually-hidden">{t("card.about")}</Dialog.Title>
              {card.error ? (
                <p className="notice error" role="alert">
                  {card.error.message}
                </p>
              ) : (
                <p className="placeholder">{t("preferences.loading")}</p>
              )}
            </>
          )}
          <div className="dialog-actions">
            {own && (
              // Your own card: the whole profile is yours to change, in Preferences.
              <Link className="button-like primary" to="/preferences" onClick={onClose} data-testid="card-edit">
                {t("card.edit")}
              </Link>
            )}
            <Dialog.Close asChild>
              <button type="button">{t("dialog.close")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
