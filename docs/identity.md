# Who is asking: the identity seam

Players and tavern Task C2. Every route learns who calls it from one place, `delve.web.auth`; no other module of
`delve.web` reads a request's cookies (`tests/test_boundaries.py::test_only_auth_reads_cookies`).

## The chain

`create_app` sets `app.state.identity` to a `ChainedIdentity`. The first identity that knows the caller wins:

| # | Identity | Reads | Gives |
|---|---|---|---|
| 1 | `OwnerTokenIdentity(token, config.token_path)` | `Authorization: Bearer <token>`, or the `delve_token` cookie; never through a proxy on this machine | `OWNER` |
| 2 | `AccountIdentity(storage, clock)` | the `delve_session` cookie, through `delve.play.logins.resolve` | `account:<id>`, with `account` set; the organiser role for an organiser or owner account |
| 3 | `SeatTokenIdentity(seat_lookup(storage))` | the `delve_seat` cookie | `seat:<id>`, with `seat` set |
| 4 | `ThisMachineIdentity(storage)` | `guard.is_this_machine(request)`, while there is no owner account | `OWNER` |

Nobody known is a 401 `{"error": "Log in to go on."}`.

- The owner token comes first: the CLI, the tests and recovery use it. It is refused through a proxy on this machine
  (`guard.from_a_proxy_here`; DEL-154, audit finding 9): it never expires and opens everything, so a tunnel's visitor
  logs in with the owner account instead. Such a request is answered 401 "The owner token works only on this machine
  and its network: over the internet, log in with your owner account." The LAN and this machine take it as before.
- The owner token follows `<data dir>/token`: `delve token --new` and `POST /api/owner-token/new` (Preferences' "Make
  a new owner token", the owner's alone, which answers the new links once) write a new one beside it and move it
  over it, and the running Delve checks the next request against the new one (it reads the file again once its
  inode, time or size changed). The old token is refused from then on, without a restart.
- The browser keeps the owner token in an `HttpOnly` cookie: the page posts the link's `#token=` once to
  `POST /api/owner-token/cookie`, which sets `delve_token` (`HttpOnly; SameSite=Strict; Path=/`, a year, `Secure`
  over HTTPS; 401 for a wrong token, 403 through a proxy here). A cookie the page wrote itself before is handed over
  the same way, once.
- An account's session comes before a seat token. A browser that kept an old seat token and logged in is the
  account; `POST /api/campaigns/{id}/seats/keep` hands the old seat to it.
- A seat token comes before this machine, since a browser here that joined a table is that seat.
- This machine is the owner only when no proxy on it forwarded the request (`guard.is_this_machine`: a loopback
  client, none of the proxy headers, and a loopback or machine address as the host), and only while there is no
  owner account. Once there is one, the owner on this machine logs in, or uses the owner token. A proxy that adds
  no headers (a default nginx `proxy_pass`, `ssh -R`, socat) looks like this machine, so make the owner account
  before opening one; `delve serve` says so while there is none. `POST /api/accounts/first-owner` works only from
  this machine, and only while there is no owner account.

`Principal.owner` is true for `OWNER` and for an account with the owner's rights (the human's ruling of
2026-10-24). Everything that means "the owner" reads it: `require_owner` (Connections, the novels), the owner seat
that `table_seat` gives at every table, and the event bus's "seated at every table".

## What follows from the principal

- `TableSeat` (`delve.web.seats.table_seat`): the owner gets their owner seat; an account gets its live seat at that
  campaign (`storage.seats.for_account`), else 403 "You have no seat at this table."; a seat token gets its own seat
  at its own table.
- `HostSeat` and `ActorSeat` build on `TableSeat`, so they work the same for every identity.
- `Organiser` is the organiser role; `Owner` is `principal.owner`.
- The voice WebSocket (`WS /api/campaigns/{id}/voice`, table voice and fixes) uses the same chain: `auth.identify`
  on the handshake (nobody known closes 4401), then `seats.connection_seat`, which is `table_seat` for any
  connection (the same seat, or the same refusal as 403 → 4403, 404 → 4404). The guard checks a WebSocket's Host and
  Origin before the app sees it (4421 or 4403). Observers may join, listening only.
- `PUT …/characters/{id}/departure` (a PC leaves the party or returns) is `Organiser` only; the DM does the same
  through its `leave_party` and `rejoin_party` tools. `PUT …/table-settings` (voice, initiative mode) is `HostSeat`:
  the host or a co-host.
- The event stream (`/api/events?campaign=<id>`): an account sees `table` events only at the table it has a seat at,
  and nothing more once its login session ends or its account is disabled.

## The login throttle

`POST /api/login` (and a wrong current password at `PUT /api/account/password`) counts failures in memory
(`LoginThrottle` in `delve.web.routes.accounts`), each for 15 minutes, and a count past its limit waits 15 minutes:

- 5 of a username from one address: that username waits at that address;
- 50 of a username from all addresses: that username waits everywhere, **except for a browser with a device cookie
  of that account** (DEL-154, audit finding 8), which instead waits after 5 failures of its own, from any address;
- 20 of any usernames from one address: that address waits.

The device cookie `delve_device` is set with every login (`HttpOnly; SameSite=Lax; Path=/`, `Secure` as the session
cookie, a year) and kept when logging out. It is `<account id>.<issued>.<nonce>.<mac>`, signed with HMAC-SHA256 by
`<data dir>/device-secret` (`delve.web.devices`), valid a year from when it was issued, for its own account only.
Without it, strangers could make any username, the owner's too, wait everywhere with ten addresses; with it, a
browser that logged in before still can, and a stranger, who has none, is held as before. It never logs anyone in.
Deleting `device-secret` (and restarting Delve) ends every device cookie.

## Sign-ups waiting for approval

A sign-up (DEL-156, `delve.web.routes.sign_up`) is an account with `pending` set. It never becomes a principal while
it waits: `accounts.authenticate` raises `AccountPending` for its right password (and answers None for a wrong one,
so a stranger learns nothing more than from any other refusal), the login route answers 403 with why, and no login
session is ever made for it. Two things end the wait: the owner or an organiser approves it on the Players page, or
the person logs in on a table's join page with that link's `join_token`, since the host who shared the link vouches for
whoever has it. Rejected, the account is deleted (only a pending account ever is). Sign-up itself is off until the owner
or an organiser opens it (`sign_up_open`); then each address may ask `PER_ADDRESS` times an hour (counted from the
username onwards, made or taken, so usernames can't be probed at will), and at most `accounts.PENDING_MAX` wait.

## Behind a proxy

Delve runs uvicorn with `proxy_headers=False`, so the client and scheme a route sees are the ones the connection
had. Delve reads the proxy's headers itself, and only from a proxy on this machine (a loopback client that isn't
this machine's own browser):

- `guard.client_address`: the rightmost `X-Forwarded-For` entry, `X-Real-IP`, then `Forwarded`'s last `for=`;
  otherwise the client's own address. `CF-Connecting-IP` and `True-Client-IP` are never read, as a proxy that
  doesn't set them passes on the visitor's own. The login and join limits count by it.
- `guard.came_over_https`: `X-Forwarded-Proto: https` or `Forwarded: proto=https`. The `delve_session` cookie is
  `Secure` only then.

A LAN client's proxy headers are ignored.

**A public proxy or tunnel must add `X-Forwarded-For`** (cloudflared does), so that Delve tells its visitors from
this machine and counts the login and join limits by their own addresses.

## Later: Keycloak (OIDC)

An `OidcIdentity` fits without changing anything that reads `current_principal`, `TableSeat`, `HostSeat` or
`ActorSeat`:

- The login page becomes a redirect to Keycloak.
- A callback route checks the token, maps its `sub` to an account by `accounts.external_id`
  (`storage.accounts.by_external_id`; the column is reserved and nothing writes it yet), and starts a login session
  as `POST /api/login` does. The session cookie and `AccountIdentity` stay as they are.
- Passwords, reset links and the login throttle become Keycloak's.

### How `sub` maps to `external_id`

`OidcIdentity` never makes an account from a token. On the callback it takes the verified token's `sub` and looks up
`storage.accounts.by_external_id(sub)`:

- **Found, and not disabled:** that account logs in (a `login_sessions` row and the `delve_session` cookie, as
  `POST /api/login` does). Its username, profile, seats, organiser and owner rights stay Delve's.
- **Not found:** the person is not logged in. Delve says so (403 "This login has no account here."). An organiser links
  a person to their account by setting its `external_id` to the `sub` (a field on the Players page, or a CLI
  command, both still to be built); until then nothing is guessed from the token's email or name. A person who
  arrives with an invite is made an account by the invite's route, with `external_id` set from the `sub`.
- **`external_id` is the Identity Provider's `sub` as a string, unique and opaque.** The issuer is part of the
  configuration of the one provider, so the column holds the `sub` alone. Null means a local account with a password;
  an account with both may log in either way until the owner removes its password.
- **The owner and organiser rights stay Delve's.** A token's claims or roles never grant them.

Nothing writes `external_id` yet; the column is reserved by migration `0020_accounts`.
