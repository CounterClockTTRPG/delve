import { useState, type ReactNode } from "react";
import Avatar from "./Avatar";
import ProfileCard from "./ProfileCard";
import type { ProfileSummary } from "./api";
import "./profile.css";

/**
 * A person's face and name, wherever an account shows (DEL-218): a button to their profile card, which shows what the
 * caller may read of it (`delve.play.profiles.card`), and for the caller's own the whole profile with a way to edit
 * it. `faceOnly` leaves the name to the button's label (a row of faces); `children` replaces the name ("Hosted by
 * Ana"). A seat without an account has no card: its face and name only.
 */
export default function PersonLink({
  profile,
  name,
  size = 22,
  faceOnly = false,
  children,
}: {
  profile: ProfileSummary | null | undefined;
  name?: string;
  size?: number;
  faceOnly?: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const label = name ?? profile?.display_name ?? "";
  const text = faceOnly ? null : <span className="person-name">{children ?? label}</span>;
  if (!profile)
    return (
      <span className={faceOnly ? "person person-face" : "person"} title={faceOnly ? label : undefined}>
        <Avatar profile={null} size={size} name={label} />
        {text}
      </span>
    );
  return (
    <>
      <button
        type="button"
        className={faceOnly ? "person person-face" : "person"}
        aria-label={faceOnly ? label : undefined}
        title={faceOnly ? label : undefined}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        <Avatar profile={profile} size={size} name={label} />
        {text}
      </button>
      {open && <ProfileCard accountId={profile.account_id} onClose={() => setOpen(false)} />}
    </>
  );
}
