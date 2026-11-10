# Players and the tavern: accounts, profiles, and table talk full screen

Date: 2026-10-24. Status: design. A project of its own, on master (9112d71 and later).

## Intent

The owner wants to test Delve **from outside the LAN, with another player**, through a public URL. The owner sets that
URL up separately (a Cloudflare Tunnel, backlog Features 35); this project gets the engine ready for it. Two things
are missing for that test:

- **Persistent players.** A player is only a seat today (`domain.campaigns.Seat`: a name, a language, a role) for one
  campaign, in the one browser that holds its token cookie (`delve_seat`). Nothing carries over to another campaign or
  device, and a lost cookie is a lost seat. Players get an **account** with a username and password, and a fleshed-out
  **profile**.
- **Tavern talk**: table talk full screen (backlog Interface 4), for the pregame while players arrive and for a
  discussion at the table.

The original design left identity out ("Real identity management or online hosting. LAN only, but the design must not
rule hosting out", spec 2026-10-17 §2, §11). This project takes the first step, on the seam that spec kept open: the
`Identity` protocol in `delve.web.auth`.

## Owner decisions (2026-10-24)

1. **Tavern talk is table talk full screen** (backlog Interface 4), not a lobby across campaigns.
2. **A player has login credentials**, a username and password managed in Delve itself for now. It must be possible to
   move to **Keycloak** later, so the accounts sit behind the identity seam.
3. **Profiles must be fleshed out**: more than a name.
4. **No Cloudflare work in this project.** The owner has a public URL and configures it separately.
5. **Budget $200, unattended**, edit mode, planning auto, design questions decided by the archmage.

## Must, though no one asked: the machine is not the owner behind a tunnel

`OwnerTokenIdentity` treats **any request from this machine** (a loopback client) as the owner. A tunnel such as
`cloudflared` runs on this machine and forwards every outside visitor from `127.0.0.1`, so behind it **every visitor
would be the owner**, with every right and every secret. That must be closed before the test:

- A request is "from this machine" only when its client is loopback **and** it carries no proxy header
  (`Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`, `CF-Connecting-IP`, `True-Client-IP`) **and** its
  `Host` is a loopback or machine address, not a name from `DELVE_ALLOWED_HOSTS`.
- Otherwise it needs the owner token, an owner login (below) or a player's login, like any LAN device.
- Tests: a loopback request with each proxy header, or with an allowed public host, is not the owner. The other
  loopback-only rules (the internal bridge routes, `invite_json`'s LAN address) get the same check.

## A. Accounts

**What an account is.** A table `accounts` (a new migration): `id` (`acc_…`), `username` (unique, compared
case-folded, 3–32 of `[a-z0-9._-]`), `password_hash`, `created_at`, `disabled_at`, `organiser` (bool), `external_id`
(null; reserved for an outside identity provider such as Keycloak's `sub`), and the profile (part B).

**Passwords.**
- Hashed with the standard library's `hashlib.scrypt` (salted, parameters stored with the hash, so they can be raised
  later), compared in constant time. No new dependency.
- At least 10 characters. Delve stores no plain password, and no password appears in a log, an event or an error.
- A player changes their own password (with the old one). An organiser can't read one, but can make a **one-time
  reset link** (valid 24 h, used once) to hand over by chat. There is no email.

**Logging in.**
- `POST /api/login` with the username and password. It sets a session cookie `delve_session` (random 32 bytes,
  stored only as its SHA-256), `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` when the request came over HTTPS
  (as the forwarded proto says, from a proxy on this machine).
- A session lasts 30 days from its last use. `POST /api/logout` ends it, and the profile page lists the sessions
  (device, last used) with **Log out everywhere**. Changing a password ends every other session.
- **Throttling:** after 5 failed logins for a username, or 20 from one address, within 15 minutes, logins for it wait
  15 minutes. The answer never says whether the username exists.
- The login page is the first thing an unknown visitor sees in place of "Open the link Delve printed at start".

**Who makes accounts. There is no open sign-up.**
- **Through an invite:** the join page (`/join/<token>`) asks a visitor who isn't logged in to **log in** or **create an
  account** (username, password, display name, language). Making it there needs the invite's token.
- **By an organiser:** a **Players** page under Preferences (organisers only) lists the accounts and can add one (which
  gives a one-time link to set the password), make a reset link, disable or enable an account, and grant or withdraw
  organiser rights.
- **For the owner:** `delve account add <username>` (the CLI asks for the password) and the same page. The owner token
  keeps working as it does, so nothing breaks. An owner who logs in as an organiser account from outside gets the
  organiser's rights, never the owner token. Whether an account can be "the owner" is the archmage's call (see Open
  questions).

**Accounts and seats.**
- `seats.account_id` (null). Joining a campaign while logged in makes the seat that account's. An account has at most
  one live seat per campaign.
- A logged-in account reaches its seats at every campaign from any device. `table_seat` finds the account's seat for
  the campaign. A new **My tables** page (the home page for a player) lists them, with each campaign's banner, its
  last session and **Play**.
- Seat tokens keep working, for seats from before accounts. A logged-in account that opens a campaign with an old
  seat's cookie can **keep this seat** to make it its own.
- Joining without an account: off. The invite always asks for an account. (The archmage may keep a guest join on the
  LAN behind an organiser switch if it costs little; it is off by default.)

**The identity seam (for Keycloak later).**
- `AccountIdentity` implements `Identity` next to `OwnerTokenIdentity`. They are chained (owner token, then the
  session, then a seat token, then this machine as defined above).
- Every route asks only `current_principal` and the seat dependencies (`TableSeat`, `HostSeat`, `ActorSeat`), never
  the cookie or the table directly.
- A later `OidcIdentity` would map a Keycloak `sub` to an account by `external_id`. Passwords would then be Keycloak's,
  and the login page would become a redirect. Nothing in this project does OIDC; the seam and the reserved column must
  make it a contained change, and the design note says how.

## B. Profiles

A player's profile lives on the account and follows them to every table.

| Field | What | Who sees it |
|---|---|---|
| Display name | 1–40 characters; the default name for a new seat | everyone at the player's tables |
| Pronouns | free text, optional (e.g. "she/her") | everyone at the player's tables |
| Avatar | one of a built-in set (at least 12, drawn to match the looks), or an uploaded picture (PNG, JPEG or WebP, at most 2 MB, cropped square and sized down to 256 px, in the blob store) | everyone at the player's tables |
| Colour | one of the looks' accent colours, for their name in table talk | everyone at the player's tables |
| Language | the default language of a new seat (a seat may still differ) | the player |
| About me | up to 500 characters, plain text | everyone at the player's tables |
| Note for the host | up to 500 characters, e.g. "new to AD&D", "no spiders please" | the host of each table they sit at |
| Time zone | optional, so a host sees the player's local time when planning a session | the hosts of the player's tables |

- **Where it shows:** table talk (avatar, name, colour), the seat indicators, the party sidebar (the player's avatar
  beside the character they play), the seats list on the campaign page, and the join page's "you are …" line. A click
  on a player's avatar opens a small **profile card** (name, pronouns, about me; the host also sees the note and the
  local time).
- **The player's own face is never their character's portrait.** Portraits stay the characters'.
- **The profile page** is the player's Preferences: Profile, Account (password, sessions), Look and "Did you know".
  Organiser-only sections (backends, connections, players) don't show to a player.
- **A seat's own name** still exists (a player may want another name at one table). It starts as the display name.
- **Privacy:** a profile is read only by people who share a table with the player, and by organisers. No route lists
  accounts to a player.
- All strings in English and Dutch.

## C. The tavern: table talk full screen

- A **Tavern** button on the table talk panel opens table talk across the play screen's middle, in place of the story
  and the composer. The composer stays below it in its Table talk mode. **Back to the story** returns.
- **When it opens by itself:** when a seat opens the play screen and the session has no beat yet (the pregame). It
  closes by itself when the first act of the session is sent, or when the host says Go. Each seat can still switch.
- In the tavern each line shows the speaker's avatar and colour (part B), and who is present (the seat indicators)
  sits above it.
- **On a phone** nothing changes: Table is already a full screen from the bottom bar.
- Shared Ask the DM answers and translations show as they do in the side panel.

## Out of scope

- The Cloudflare Tunnel itself, DNS and a public-URL setting (owner, separately; backlog Features 35). The public host
  goes in `DELVE_ALLOWED_HOSTS`, which exists already.
- Keycloak or any OIDC login (only the seam).
- Email (no verification, no reset by mail).
- A lobby across campaigns, private messages between players.

## Open questions for the archmage (decide and record)

1. Can an account be **the owner** (the install's owner logging in from outside), or only an organiser? Recommended:
   an organiser account only. The owner token stays the one owner credential.
2. Does a guest join without an account stay on the LAN behind a switch, or go? Recommended: it goes, unless it is
   nearly free.
3. Does the avatar set come from the looks' textures, generated portraits or simple drawn emblems? Recommended:
   simple SVG emblems (heraldic shapes in the looks' colours), shipped with the web app.

## Done when

- A second person, on another device, can be given an invite, make an account, log in, set a profile with an
  uploaded avatar, sit at a table, talk in the tavern, play a beat, log out, and log in on a third device to find the
  same seat, with nothing of the owner's reachable.
- A request from this machine with a proxy header, or with a public host, is not the owner (tests).
- Passwords are hashed with scrypt; login throttling, session expiry, Log out everywhere and the one-time reset link
  work (tests).
- Every route that reads a seat finds an account's seat; old seat tokens still work (tests).
- The tavern opens in the pregame and closes at the first act (tests, browser spec).
- `make ci` green in a fresh clone, and `make e2e-browser` with a new two-browser spec: an account joins, talks in the
  tavern and plays.
- The glossary gains **Account**, **Profile** and **Tavern**. `docs/backlog.md` marks Features 34 and Interface 4 done.
