import type { CSSProperties } from "react";
import { COLOURS, avatarUrl, type ProfileSummary } from "./api";
import { Emblem } from "./emblems";
import "./profile.css";

/**
 * A player's face at the table (players and tavern Task G1): their uploaded picture, or their emblem on a field of
 * their colour, round, with a ring in the colour. A seat without a profile (the owner's, a seat from before
 * accounts) gets a plain dot of the ink colour, or with `name` that name's first letter in a ring (the talk, so every
 * line shows who said it). It is the player's, never their character's portrait. With `onClick` it is a button that
 * opens the profile card.
 */
export default function Avatar({
  profile,
  size = 32,
  onClick,
  name,
  src,
}: {
  profile: ProfileSummary | null | undefined;
  size?: number;
  onClick?: () => void;
  name?: string;
  /** Where the uploaded picture is served, in place of the profile's own route (the board's, DEL-297). */
  src?: string;
}) {
  const initial = name?.trim() ? Array.from(name.trim())[0].toUpperCase() : "";
  if (!profile && initial)
    return (
      <span className="avatar avatar-initial" style={{ width: size, height: size, fontSize: size * 0.45 }} aria-hidden="true">
        {initial}
      </span>
    );
  if (!profile) return <span className="avatar avatar-none" style={{ width: size, height: size }} aria-hidden="true" />;
  const colour = profile.colour in COLOURS ? (profile.colour as keyof typeof COLOURS) : "teal";
  const style = { width: size, height: size, "--avatar-colour": COLOURS[colour] } as CSSProperties;
  const face =
    "picture" in profile.avatar ? (
      <img src={src ?? avatarUrl(profile.account_id, profile.avatar.picture)} alt={profile.display_name} width={size} height={size} />
    ) : (
      <Emblem name={profile.avatar.emblem} title={profile.display_name} />
    );
  const emblem = "emblem" in profile.avatar ? profile.avatar.emblem : undefined;
  if (onClick)
    return (
      <button
        type="button"
        className="avatar"
        style={style}
        data-colour={colour}
        data-emblem={emblem}
        aria-label={profile.display_name}
        onClick={onClick}
      >
        {face}
      </button>
    );
  return (
    <span className="avatar" style={style} data-colour={colour} data-emblem={emblem}>
      {face}
    </span>
  );
}
