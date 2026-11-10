# Players and the Tavern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second person, on another device and through the owner's public URL, gets an invite, makes an account,
logs in, sets a profile with an uploaded avatar, sits at a table, talks in the tavern, plays a beat, logs out, and
logs in on a third device to find the same seat, and nothing of the owner's is reachable.

**Architecture:** Accounts (`accounts`, `account_links`, `login_sessions`, `seats.account_id`) live in storage behind
`delve.play.accounts`/`delve.play.logins`; the web reaches them only through the identity seam: an `AccountIdentity`
chained after the owner token in `delve.web.auth`, and the seat dependencies (`TableSeat`…), which find an account's
seat per campaign. Profiles are fields of the account, read through one privacy check. The tavern is the web's table
talk panel full screen, opened by a `pregame` flag of `play/state`.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy/Alembic on SQLite, `hashlib.scrypt`, Pillow (already a dependency),
React + TanStack Query, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-24-players-and-tavern-design.md` (owner-approved 2026-10-24; read it first).
Words: `docs/glossary.md`. Values: `docs/data-dictionary.md`. Rules: `GUILD.md`.

## Decisions (the archmage's, on the spec's open questions, 2026-10-24)

1. ~~**An account is never the owner.**~~ Replaced by the human's ruling: see "Owner accounts (human ruling)" below.
   An *organiser* account (not an owner one) still gets 403 on every `Owner` route (Connections, novels).
2. **Guest join without an account is removed.** Every invite asks for an account; there is no switch.
   `POST /api/join/{token}` needs a logged-in account. Seat tokens made before this project keep working.
3. **The avatar set is 12 simple SVG heraldic emblems**, drawn in the player's colour (the looks' accent colours),
   shipped with the web app as inline React SVG (`web/src/profile/emblems.tsx`), nothing generated.

Builder's calls this plan makes (record them in the chronicle with the three above):

- Login sessions are `login_sessions` (table) and `LoginSession` (type): `Storage.sessions` is already the game's
  evenings of play. The UI says "Where you're logged in", never "session" for them.
- Only the owner grants or withdraws an account's organiser rights, and disables an organiser account (as today only
  the owner makes a seat an organiser). An organiser may list accounts, add one, make a reset link, and disable or
  enable a player account.
- "Log out everywhere" ends every login session of the account, this one included.
- The `delve_session` cookie lives a year (like `delve_seat`); the server ends the session 30 days after its last use.
- Talk entries stay as stored (`{seat_id, name, …}`); the web shows a line's avatar and colour from the seat list's
  profile by `seat_id`, so a changed avatar shows on old lines too.
- `colour` is one of four names, the looks' accents: `teal` (#2c7a6b, Delve today), `jade` (#62b9a5, Delve today
  dark), `gold` (#e0bc74, Gold and wood), `ember` (#e08a3c, Dark dungeon). The colour marks the avatar's ring and the
  talk line's left bar; the name's text stays in the ink colour, so every look keeps its contrast.
- The account's event stream sees a table's events only at the table of its seat for the stream's `?campaign=`; an
  organiser account sees `organisers` events too, but no other table's.

## Owner accounts (human ruling, 2026-10-24)

This replaces decision 1 above: accounts carry the authorizations, and the owner token stops being the way in. Where
this section and a task below differ, this section wins.

- **B (done as built):** `accounts.owner BOOLEAN NOT NULL DEFAULT 0`, beside `organiser`, in `0020_accounts`;
  `Account.owner`; `AccountRepository.create(…, owner=False)` and `set_owner(id, owner)`. `delve.play.accounts` adds
  `create_account(…, owner=False)`, `has_owner_account(storage)`, `create_first_owner(storage, username, password, *,
  display_name=None, language="en")` (`AccountConflict` once any owner account exists), `set_owner(storage,
  account_id, owner, *, by_owner: bool)`, and a required `by_owner` on `set_organiser` and `set_disabled`: only an
  owner grants or withdraws owner or organiser rights, or disables or enables an owner's or an organiser's account
  (`NotAllowed`, 403); an organiser may disable or enable a player's. The last enabled owner account is never
  demoted or disabled (`AccountConflict`, 409). `delve account add <username> --owner` makes an owner account.
- **C:** an owner account's session resolves to the owner principal: `account_principal` keeps
  `id=f"account:{account.id}"` and `account=account`, with roles `{"organiser"}`, and `Principal.owner` becomes
  `self.id == "owner" or (self.account is not None and self.account.owner)`; every check that means "the owner"
  reads `principal.owner` (`require_owner`, the owner's seat at every table, `EventBus.may_see`), from any device and
  through the tunnel. `by_owner=principal.owner` is what the routes pass to the service. `logins.disable` passes it
  on. `POST /api/accounts/first-owner` `{username, password, display_name?}`: only while `has_owner_account` is
  False and only when `guard.is_this_machine(request)` (else 403), 201 with the new account logged in. `GET /api/me`
  says `owner_account_exists` to an unknown caller from this machine, so the login page knows to offer it. The
  Players API gains `owner` on `PUT /api/accounts/{id}` and in the list. The owner token (bearer and cookie),
  this machine as the owner, and old seat tokens all stay; removing owner-token auth is a later quest.
- **E:** the login page (username and password) replaces the token page entirely: no "Have the owner's token?"
  disclosure, no `login.ownerToken`, and the UI never asks for or shows the owner token. While no owner account
  exists, a browser on this machine sees "Make the owner account" on the login page (`login-first-owner`). The
  Players page shows and (for an owner) changes the owner right.
- **`delve serve`** (C, `__main__.start_message`): prints the login URL, and when no owner account exists the hint
  `Make the owner account: delve account add <username> --owner` (or open the login page on this machine), instead
  of the token link. `delve token` stays, for recovery.
- **H:** the e2e host logs in as an owner account (made with `delve account add --owner` before the server starts,
  or through the first-owner route) where it can; existing specs may keep the owner token where changing them costs
  a lot.
- **S:** the glossary's **Account** reads "…it may be an organiser, or hold the owner's rights."; the data dictionary
  gains `accounts.owner`; GUILD.md says the owner logs in with an owner account and the token is for the CLI,
  tests and recovery.

## Global Constraints

- Every Global Constraint of `GUILD.md` holds (ports, the CSP, JSON bodies, `Origin`/`Host` checks, `{"error": …}`
  errors, the dependency rules: only `delve.storage` imports `sqlalchemy`, only `delve.web` imports `fastapi`).
- Never touch the live Delve (port 7810, `delve.service`, `~/.local/share/delve`); every manual run uses a tmp
  `DELVE_DATA_DIR` and a free high port.
- No new dependency. Passwords: `hashlib.scrypt`; avatars: Pillow.
- Existing seat tokens (`delve_seat`) and the owner token (`delve_token`) keep working unchanged.
- Usernames: case-folded, then `^[a-z0-9._-]{3,32}$`, unique. Passwords: at least 10 characters (at most 1024).
- Display name 1–40 characters; pronouns at most 40; about me and note for the host at most 500; plain text.
- Login: 5 failed logins for a username, or 20 from one address, within 15 minutes → that username or address waits
  15 minutes. The answer never says whether a username exists.
- Sessions: cookie `delve_session`, 32 random bytes (`secrets.token_urlsafe(32)`), stored only as its SHA-256 hex,
  `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` only when a proxy on this machine says the request came over HTTPS;
  ended 30 days after last use. Reset and set-password links: valid 24 hours, used once.
- Avatar upload: `image/png`, `image/jpeg` or `image/webp`, at most 2 MB, cropped square, 256 px, in the blob store.
- No password, token or hash in a log, an event, an error or an API answer.
- Every user-visible string in `web/src/i18n/en.json` and `nl.json`; `nl` has every key `en` has.
- Commit messages end with `(players and tavern Task <id>)`; module docstrings cite "players and tavern Task <id>".
- `make ci` green before each package is finished; `make e2e-browser` green at the end (package H).

## Review Focus

1. **An account's event stream on another table**: today `EventBus.may_see` lets any principal without a seat see
   every table's events as "the owner, seated at every table". An account listening with `?campaign=A` must get no
   event of campaign B, and with no `campaign`, no table event at all → Task C3
   `test_account_stream_sees_only_its_own_table`.
2. **An organiser account on an owner route**: `require_owner` today lets through any principal without a seat, so an
   account would pass. It must get 403 on Connections and the novels → Task C2 `test_organiser_account_is_not_the_owner`.
3. **Joining twice** (a reload, two tabs, a double click on Play): an account gets its one live seat back, never a
   second; a race on the unique index answers the existing seat → Task C5 `test_join_twice_keeps_one_seat`.
4. **A username typed in other case or with spaces** (`" Ana "`, `ANA`): it is `ana` for making, logging in and the
   throttle → Task B2 `test_username_is_case_folded_everywhere`, Task C4 `test_login_any_case`.
5. **A phone photo as avatar**: EXIF-rotated JPEG, a PNG sent as `image/jpeg`, a 1×20000 strip, an animated WebP, a
   pixel bomb: upright, centre-cropped, first frame, 400 for a mismatch, 422 past the pixel cap → Task D2
   `test_avatar_exif_rotated_upright`, `test_avatar_type_mismatch_is_400`, `test_avatar_pixel_bomb_is_422`,
   `test_avatar_strip_is_centre_cropped`.

---

## Work packages and order

| Package | Needs | Runs in parallel with | Owns (besides `web/src/i18n/*.json`, which every package may add keys to) |
|---|---|---|---|
| Task 0 (done, Ravi) | — | — | `delve.web.guard.is_this_machine(connection)` |
| B Accounts core | Task 0 | F | see B |
| C Login, sessions and the seam | B | F | see C |
| D Profiles backend | C | E, F | see D |
| E Account web pages | C | D, F | see E |
| F Tavern | — | B, C, D, E | see F |
| G Profiles web | D, E, F | — | see G |
| H Two-browser e2e spec | G | — | see H |
| S Docs | H | — | see S |

A file not in a package's list is not that package's to edit; if a package finds it must, it asks the archmage.
Between C's merge and H, `make e2e-browser` fails on the specs that join without an account (not in `make ci`); H
mends them.

**Task 0 (done).** `delve.web.guard.is_this_machine(connection: HTTPConnection) -> bool`: the client is loopback,
the request carries none of `Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`, `X-Real-IP`, `CF-Connecting-IP`,
`True-Client-IP`, and its `Host` is a loopback or machine address, not one from `DELVE_ALLOWED_HOSTS`.
`OwnerTokenIdentity`, `bridge_refusal` and `invite_json` use it. Everything below builds on it; nothing below calls
`request.client.host in LOOPBACK` again.

---

## B. Accounts core

**Owns:** `src/delve/storage/migrations/versions/0020_accounts.py`, `src/delve/domain/accounts.py`,
`src/delve/domain/campaigns.py` (`Seat.account_id`), `src/delve/storage/interfaces.py` (`AccountRepository`,
`AccountLinkRepository`, `SeatRepository` additions, `Storage`), `src/delve/storage/sqlite/tables.py`,
`src/delve/storage/sqlite/accounts_repo.py`, `src/delve/storage/sqlite/seats_repo.py`,
`src/delve/storage/sqlite/__init__.py`, `src/delve/play/passwords.py`, `src/delve/play/accounts.py`,
`src/delve/__main__.py`, `tests/conftest.py` (the fast-scrypt fixture), `tests/storage/contract.py`,
`tests/storage/test_migrations.py`, `tests/storage/test_migration_0020.py`, `tests/domain/test_accounts.py`,
`tests/play/test_passwords.py`, `tests/play/test_accounts.py`, `tests/test_cli.py`.

### Task B1: The migration, the domain and the repositories

**Files:**
- Create: `src/delve/storage/migrations/versions/0020_accounts.py`, `src/delve/domain/accounts.py`,
  `src/delve/storage/sqlite/accounts_repo.py`, `tests/storage/test_migration_0020.py`, `tests/domain/test_accounts.py`
- Modify: `src/delve/domain/campaigns.py`, `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/tables.py`,
  `src/delve/storage/sqlite/seats_repo.py`, `src/delve/storage/sqlite/__init__.py`, `tests/storage/contract.py`,
  `tests/storage/test_migrations.py` (`HEAD = "0020_accounts"`)

**Interfaces:**
- Migration `0020_accounts`, revises `0019_campaign_maps`:
  - `accounts`: `id TEXT PK` (`acc_…`), `username TEXT NOT NULL UNIQUE` (stored case-folded), `password_hash TEXT
    NULL` (null until a set-password link is used), `created_at TEXT NOT NULL`, `disabled_at TEXT NULL`, `organiser
    BOOLEAN NOT NULL DEFAULT 0`, `external_id TEXT NULL UNIQUE` (reserved for an outside identity provider's subject,
    such as Keycloak's `sub`; nothing writes it in this project), and the profile: `display_name TEXT NOT NULL`,
    `pronouns TEXT NOT NULL DEFAULT ''`, `avatar_emblem TEXT NULL`, `avatar_sha TEXT NULL`, `colour TEXT NOT NULL
    DEFAULT 'teal'`, `language TEXT NOT NULL DEFAULT 'en'`, `about TEXT NOT NULL DEFAULT ''`, `host_note TEXT NOT NULL
    DEFAULT ''`, `time_zone TEXT NULL`.
  - `account_links`: `token_hash TEXT PK`, `account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE`,
    `kind TEXT NOT NULL` (`set-password` | `reset-password`), `created_at`, `expires_at`, `used_at NULL`.
  - `ALTER TABLE seats ADD COLUMN account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL` (plain `ALTER`, as
    `0010_seats` does: a batch would copy and drop `seats`, and the drop would cascade), and
    `CREATE UNIQUE INDEX uq_seats_account_live ON seats (campaign_id, account_id) WHERE account_id IS NOT NULL AND
    left_at IS NULL`.
  - Downgrade drops the index, the column (`ALTER TABLE seats DROP COLUMN account_id`) and both tables.
- `delve.domain.accounts`:
  - `USERNAME = re.compile(r"[a-z0-9._-]{3,32}")`, `PASSWORD_MIN = 10`, `PASSWORD_MAX = 1024`.
  - `EMBLEMS = ("lion", "eagle", "stag", "boar", "wolf", "dragon", "tower", "key", "sword", "crown", "moon", "oak")`.
  - `COLOURS = ("teal", "jade", "gold", "ember")`.
  - `LINK_KINDS = ("set-password", "reset-password")`, `LINK_HOURS = 24`.
  - `def default_emblem(username: str) -> str` → `EMBLEMS[int(sha256(username).hexdigest(), 16) % len(EMBLEMS)]`.
  - `@dataclass(frozen=True) class Profile: display_name: str; pronouns: str = ""; avatar_emblem: str | None = None;
    avatar_sha: str | None = None; colour: str = "teal"; language: str = "en"; about: str = ""; host_note: str = "";
    time_zone: str | None = None`.
  - `@dataclass(frozen=True) class Account: id: str; username: str; profile: Profile; organiser: bool = False;
    created_at: str = ""; disabled_at: str | None = None; external_id: str | None = None; has_password: bool = False`.
    The hash is never a field: it is read and written only by the repository's two password methods.
  - `@dataclass(frozen=True) class AccountLink: account_id: str; kind: str; created_at: str; expires_at: str;
    used_at: str | None = None`.
- `Seat` gains `account_id: str | None = None` (last field).
- `AccountRepository` (`storage.accounts`): `create(username: str, profile: Profile, *, organiser: bool = False) ->
  Account` (`ValueError` for a username in use); `get(id) -> Account | None`; `by_username(username) -> Account |
  None` (exact, already folded); `by_external_id(external_id) -> Account | None`; `list() -> list[Account]` (oldest
  first); `password_hash(id) -> str | None`; `set_password_hash(id, password_hash: str) -> None`;
  `save_profile(id, profile: Profile) -> Account`; `set_organiser(id, organiser: bool) -> Account`;
  `set_disabled(id, disabled_at: str | None) -> Account`.
- `AccountLinkRepository` (`storage.account_links`): `put(token_hash, link: AccountLink) -> None`; `get(token_hash)
  -> AccountLink | None`; `use(token_hash, used_at: str) -> bool` (False when it was already used: an
  `UPDATE … WHERE used_at IS NULL`); `drop_unused(account_id) -> None`.
- `SeatRepository`: `create(…, account_id: str | None = None)` (`ValueError` for a second live seat of the account
  at the campaign, too); `for_account(account_id: str, campaign_id: str) -> Seat | None` (the live one);
  `of_account(account_id: str) -> list[Seat]` (live, oldest first); `save` stores `account_id`.

- [ ] **Step 1: Failing tests**
  - `tests/storage/test_migration_0020.py::test_old_seat_tokens_still_find_their_seats`: a database migrated to
    `0019_campaign_maps` with a seat whose `token_hash` is set → upgrade → `seats.by_token_hash(h)` finds it, its
    `account_id is None`; `test_downgrade_drops_accounts` (back to 0019: no `accounts`, no `seats.account_id`).
  - `tests/storage/contract.py`: `test_account_round_trip` (create, get, by_username, save_profile, set_organiser,
    set_disabled), `test_username_in_use_is_value_error`, `test_password_hash_only_through_its_methods`
    (`asdict(account)` has no key holding the hash), `test_link_used_once` (`use` True, then False),
    `test_one_live_seat_per_account_and_campaign` (second `create` with the same account → `ValueError`; after
    the first leaves, a new one is allowed), `test_for_account_and_of_account`.
  - `tests/domain/test_accounts.py::test_emblems_and_colours` (exactly the 12 names above, in that order, and the
    4 colours), `test_default_emblem_is_stable` (same username → same emblem, always one of `EMBLEMS`).
- [ ] **Step 2: Run** `uv run pytest tests/storage tests/domain/test_accounts.py -q` → FAIL.
- [ ] **Step 3: Implement** the migration, the dataclasses, the tables in `tables.py` and the two repositories
  (`SqliteAccountRepository`, `SqliteAccountLinkRepository` in `accounts_repo.py`), wired in
  `storage/sqlite/__init__.py` as `self.accounts`, `self.account_links`.
- [ ] **Step 4: Run** the same → PASS; `uv run lint-imports` → contracts kept.
- [ ] **Step 5: Commit** `Accounts: the accounts and account_links tables, seats.account_id (players and tavern Task B1)`.

### Task B2: Passwords, the accounts service and the CLI

**Files:**
- Create: `src/delve/play/passwords.py`, `src/delve/play/accounts.py`, `tests/play/test_passwords.py`,
  `tests/play/test_accounts.py`
- Modify: `src/delve/__main__.py` (`account add`), `tests/conftest.py`, `tests/test_cli.py`

**Interfaces:**
- `delve.play.passwords`:
  - `SCRYPT_N = 2**15`, `SCRYPT_R = 8`, `SCRYPT_P = 1`, `SALT_BYTES = 16`, `KEY_BYTES = 32`,
    `MAXMEM = 64 * 1024 * 1024`.
  - `def hash_password(password: str) -> str` → `"scrypt$<n>$<r>$<p>$<salt b64>$<key b64>"` (url-safe base64, no
    padding), a fresh salt each time.
  - `def check_password(password: str, stored: str | None) -> bool`: recomputes with the stored parameters and
    compares with `hmac.compare_digest`; False for None or a malformed hash, never raises.
  - `def dummy_check(password: str) -> None`: hashes against a fixed stored hash, so an unknown username costs what
    a known one does.
- `delve.play.accounts` (refusals are `PlayError` from `delve.play.context`; `AccountConflict(PlayError)` is 409):
  - `def username_of(raw: str) -> str`: `raw.strip().casefold()`, then `USERNAME.fullmatch`; else `PlayError("A
    username has 3 to 32 characters: a to z, 0 to 9, '.', '_' and '-'.")`.
  - `def check_new_password(password: str) -> None`: `PlayError("A password has at least 10 characters.")` under
    `PASSWORD_MIN`, `PlayError("A password has at most 1024 characters.")` over `PASSWORD_MAX`.
  - `def create_account(storage, username: str, password: str | None, *, display_name: str | None = None, language:
    str = "en", organiser: bool = False) -> Account`: folds and checks the username (`AccountConflict("That username
    is taken.")`), checks the password when given, profile `Profile(display_name or username, language=language,
    avatar_emblem=default_emblem(username))`, one transaction.
  - `def authenticate(storage, username: str, password: str) -> Account | None`: None for a username that doesn't
    fold to a valid one, an unknown one (after `dummy_check`), a disabled account, one without a password, or a wrong
    password.
  - `def change_password(storage, account_id: str, old: str, new: str) -> None`: `NotAllowed("Your current password
    is wrong.")` (403, `delve.play.seats.NotAllowed`) when `old` fails.
  - `def make_link(storage, account_id: str, kind: str, now: datetime) -> str`: drops the account's unused links,
    stores the new one's SHA-256 with `expires_at = now + LINK_HOURS`, returns the token (`secrets.token_urlsafe(32)`).
  - `def link_for(storage, token: str, now: datetime) -> tuple[Account, AccountLink] | None`: None when unknown,
    used, expired or its account disabled.
  - `def use_link(storage, token: str, password: str, now: datetime) -> Account`: `check_new_password`, then in one
    transaction `use` (False → `PlayError("This link has been used: ask for a new one.")`) and `set_password_hash`.
  - `def set_disabled(storage, account_id: str, disabled: bool, now: datetime) -> Account`,
    `def set_organiser(storage, account_id: str, organiser: bool) -> Account`. Ending sessions is C's (Task C1 wraps
    these).
- CLI: `delve account add <username> [--organiser] [--display-name NAME]`: asks `Password: ` and `Again: ` with
  `getpass`; different → exit 1 "The passwords differ."; a refusal → its message on stderr, exit 1; done → `Account
  <username> made.`, exit 0. It opens storage as `house-rules import` does (migrating first).
- `tests/conftest.py`: an autouse fixture `fast_scrypt` sets `delve.play.passwords.SCRYPT_N = 2**10`; a test marked
  `@pytest.mark.real_scrypt` keeps `2**15`.

- [ ] **Step 1: Failing tests**
  - `tests/play/test_passwords.py`: `test_hash_round_trip` (check True for the password, False for another);
    `test_salted` (two hashes of one password differ); `test_parameters_stored` (`real_scrypt`: the hash starts
    `scrypt$32768$8$1$`, and a hash made with `SCRYPT_N = 2**10` still checks after `SCRYPT_N` is raised);
    `test_malformed_is_false` (`""`, `None`, `"scrypt$x"`, `"bcrypt$…"` → False, no exception).
  - `tests/play/test_accounts.py`: `test_username_is_case_folded_everywhere` (`create_account(" Ana ")` → `ana`;
    `create_account("ANA")` → `AccountConflict`; `authenticate("ANA", pw)` finds it);
    `test_username_rules` (`"ab"`, 33 characters, `"an a"`, `"ana!"`, `"émile"` refused; `"a.b_c-1"` kept);
    `test_password_at_least_10`; `test_authenticate_refuses` (unknown, wrong, disabled, no password → None);
    `test_change_password_needs_the_old`; `test_link_valid_24_hours_used_once` (at +23 h 59 m found, at +24 h None;
    `use_link` twice → the second `PlayError`); `test_new_link_drops_the_old`;
    `test_no_password_in_errors` (every `PlayError` message of this module holds no argument's password).
  - `tests/test_cli.py::test_account_add` (monkeypatched `getpass`: made, then `authenticate` works),
    `test_account_add_passwords_differ` (exit 1), `test_account_add_taken` (exit 1, "That username is taken.").
- [ ] **Step 2: Run** `uv run pytest tests/play/test_passwords.py tests/play/test_accounts.py tests/test_cli.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same → PASS; `make ci` → green.
- [ ] **Step 5: Commit** `Accounts: scrypt passwords, the accounts service, one-time links and delve account add (players and tavern Task B2)`.

---

## C. Login, sessions and the seam

**Owns:** `src/delve/storage/migrations/versions/0021_login_sessions.py`, `src/delve/domain/accounts.py`
(`LoginSession` only), `src/delve/storage/interfaces.py` (`LoginSessionRepository`),
`src/delve/storage/sqlite/tables.py`, `src/delve/storage/sqlite/login_sessions_repo.py`,
`src/delve/storage/sqlite/__init__.py`, `src/delve/play/logins.py`, `src/delve/web/auth.py`,
`src/delve/web/seats.py`, `src/delve/web/events.py`, `src/delve/web/guard.py` (`client_address`,
`came_over_https`), `src/delve/web/app.py`, `src/delve/web/routes/accounts.py`, `src/delve/web/routes/players.py`,
`src/delve/web/routes/join.py`, `src/delve/web/routes/seats.py` (`/api/me`, `change_seat`, `leave`),
`src/delve/web/routes/rulesets.py` (`ruleset_reader`), `docs/identity.md`, `tests/web/conftest.py`,
`tests/web/test_auth.py`, `tests/web/test_seats_identity.py`, `tests/web/test_join_api.py`,
`tests/web/test_login_api.py`, `tests/web/test_players_api.py`, `tests/web/test_account_seats.py`,
`tests/web/test_events_accounts.py`, `tests/play/test_logins.py`, `tests/storage/test_migrations.py`,
`tests/storage/contract.py`, `tests/test_boundaries.py`, and the joins of `tests/e2e/test_a_faithful_book.py`,
`test_a_journey.py`, `test_a_novel.py`, `test_a_table_of_three.py`, `test_read_a_world_map.py`.

### Task C1: Login sessions in storage and `delve.play.logins`

**Files:**
- Create: `src/delve/storage/migrations/versions/0021_login_sessions.py`,
  `src/delve/storage/sqlite/login_sessions_repo.py`, `src/delve/play/logins.py`, `tests/play/test_logins.py`
- Modify: `src/delve/domain/accounts.py`, `src/delve/storage/interfaces.py`, `src/delve/storage/sqlite/tables.py`,
  `src/delve/storage/sqlite/__init__.py`, `tests/storage/contract.py`, `tests/storage/test_migrations.py`
  (`HEAD = "0021_login_sessions"`)

**Interfaces:**
- Migration `0021_login_sessions`, revises `0020_accounts`: `login_sessions`: `id TEXT PK` (`lgn_…`),
  `account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE`, `token_hash TEXT NOT NULL UNIQUE`,
  `created_at`, `last_used_at`, `device TEXT NOT NULL DEFAULT ''` (the User-Agent, cut to 200 characters),
  `address TEXT NOT NULL DEFAULT ''`; index `ix_login_sessions_account`.
- `@dataclass(frozen=True) class LoginSession: id: str; account_id: str; created_at: str; last_used_at: str;
  device: str = ""; address: str = ""` in `delve.domain.accounts`.
- `LoginSessionRepository` (`storage.login_sessions`): `create(account_id, token_hash, device, address, now: str) ->
  LoginSession`; `by_token_hash(token_hash) -> LoginSession | None`; `touch(id, now: str) -> None`;
  `list(account_id) -> list[LoginSession]` (newest use first); `end(id) -> None`; `end_all(account_id, *, but:
  str | None = None) -> None`.
- `delve.play.logins`: `SESSION_DAYS = 30`, `TOUCH_EVERY_S = 60`;
  - `def start(storage, account_id: str, device: str, address: str, now: datetime) -> str` (the token);
  - `def resolve(storage, token: str, now: datetime) -> tuple[Account, LoginSession] | None`: None when unknown,
    unused for 30 days (and then ended), or its account disabled; touches `last_used_at` when older than
    `TOUCH_EVERY_S`;
  - `def change_password(storage, account_id, old, new, *, keep: str) -> None`: `accounts.change_password`, then
    `end_all(…, but=keep)`, one transaction;
  - `def disable(storage, account_id, disabled: bool, now) -> Account`: `accounts.set_disabled`, and when disabling
    `end_all`, one transaction;
  - `def use_link(storage, token, password, now) -> Account`: `accounts.use_link`, then `end_all` (a reset ends
    every login).

- [ ] **Step 1: Failing tests** (`tests/play/test_logins.py`, `tests/storage/contract.py`):
  `test_session_round_trip`, `test_session_ends_30_days_after_last_use` (used at day 29 → alive at day 58; unused
  from day 0 → None at day 30 and its row gone), `test_touch_at_most_once_a_minute`, `test_disabled_account_has_no_session`,
  `test_password_change_ends_other_sessions` (three sessions; change with `keep` = the first → only the first lives),
  `test_reset_link_ends_every_session`, `test_token_stored_only_as_hash` (no column holds the token).
- [ ] **Step 2: Run** `uv run pytest tests/play/test_logins.py tests/storage -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Accounts: login sessions, 30 days from their last use (players and tavern Task C1)`.

### Task C2: The identity chain

**Files:**
- Modify: `src/delve/web/auth.py`, `src/delve/web/app.py`, `src/delve/web/guard.py`, `tests/web/test_auth.py`,
  `tests/test_boundaries.py`
- Create: `docs/identity.md`

**Interfaces:**
- `Principal` gains `account: Account | None = None` and the property `owner -> bool` (`self.id == "owner"`).
- `SESSION_COOKIE = "delve_session"`; `def session_token(request) -> str | None`; `def seat_token(request) -> str |
  None` (the two cookie reads; no other module under `delve.web` reads `request.cookies`).
- `def account_principal(account: Account, login: LoginSession) -> Principal` → `id=f"account:{account.id}"`, roles
  `{"organiser"}` when `account.organiser`, `seat=None`, `account=account`, and `login_hash` (a new `Principal`
  field, `str | None = None`): the SHA-256 of the presented `delve_session`, for the event stream (Task C3).
- Identities, each implementing `Identity`: `OwnerTokenIdentity(token)` (the bearer or `delve_token`, nothing else);
  `AccountIdentity(storage, clock)` (the `delve_session` cookie through `logins.resolve`);
  `SeatTokenIdentity(seat_for_token)` (the `delve_seat` cookie); `ThisMachineIdentity()` (`OWNER` when
  `guard.is_this_machine(request)`); `ChainedIdentity(*identities)` (the first non-None). `create_app` sets
  `app.state.identity = ChainedIdentity(OwnerTokenIdentity(token), AccountIdentity(storage, app.state.clock),
  SeatTokenIdentity(seat_lookup(storage)), ThisMachineIdentity())`.
- `require_owner`: 403 `ONLY_THE_OWNER` unless `principal.owner`.
- `NEEDS_TOKEN` becomes `NEEDS_LOGIN = "Log in to go on."` (the 401 detail).
- `guard.client_address(connection) -> str`: for a request from a proxy on this machine (loopback client with a proxy
  header) the first of `CF-Connecting-IP`, `True-Client-IP`, `X-Real-IP`, the rightmost `X-Forwarded-For` entry,
  `Forwarded`'s last `for=`; otherwise the client's own address (a LAN client's proxy headers are ignored).
- `guard.came_over_https(connection) -> bool`: the URL's scheme is https, or a loopback client says
  `X-Forwarded-Proto: https` or `Forwarded: …proto=https`.
- `docs/identity.md`: the chain and its order; what each identity reads; how a later `OidcIdentity` fits: the login
  page becomes a redirect to Keycloak, a callback route maps the token's `sub` to an account by
  `accounts.external_id` (`storage.accounts.by_external_id`) and starts a login session as `POST /api/login` does,
  passwords and resets become Keycloak's, and nothing that reads `current_principal`, `TableSeat`, `HostSeat` or
  `ActorSeat` changes.

- [ ] **Step 1: Failing tests** (`tests/web/test_auth.py`, `tests/test_boundaries.py`):
  - `test_chain_order` (owner token beats a session; a session beats a seat token; a seat token beats this machine;
    nothing → None);
  - `test_session_cookie_is_the_account` (a `lan` client with a live `delve_session` → `account:acc_…`);
  - `test_ended_session_is_nobody_from_outside` (an ended session from a `lan` client, and from a loopback client
    with `X-Forwarded-For` → 401 `{"error": "Log in to go on."}`);
  - `test_organiser_account_is_not_the_owner` (organiser account → 403 on `GET /api/connections` and
    `POST /api/novels`; 200 on `GET /api/campaigns`, an `Organiser` route);
  - `test_client_address_trusts_only_a_proxy_here` (loopback + `CF-Connecting-IP: 203.0.113.9` → `203.0.113.9`;
    LAN client + the same header → the LAN address; `X-Forwarded-For: 1.1.1.1, 203.0.113.9` → `203.0.113.9`);
  - `test_came_over_https` (loopback + `X-Forwarded-Proto: https` → True; LAN + it → False; nothing → False);
  - `tests/test_boundaries.py::test_only_auth_reads_cookies` (no module under `src/delve/web` but `auth.py`
    contains `.cookies`).
- [ ] **Step 2: Run** `uv run pytest tests/web/test_auth.py tests/test_boundaries.py -q` → FAIL.
- [ ] **Step 3: Implement**, and write `docs/identity.md`.
- [ ] **Step 4: Run** `uv run pytest tests/web -q` → PASS (every existing identity test unchanged in meaning).
- [ ] **Step 5: Commit** `Identity: the owner token, the account's session, the seat token, then this machine (players and tavern Task C2)`.

### Task C3: Seats and the event stream for accounts

**Files:**
- Modify: `src/delve/web/seats.py`, `src/delve/web/events.py`, `src/delve/web/routes/rulesets.py`,
  `src/delve/web/routes/seats.py`
- Create: `tests/web/test_account_seats.py`, `tests/web/test_events_accounts.py`

**Interfaces:**
- `table_seat(request, campaign_id)`: the owner (`principal.owner`) → the owner seat, as today; an account → its
  live seat there (`storage.seats.for_account`), else 403 `NO_SEAT = "You have no seat at this table."` (404 for an
  unknown campaign); a seat token → as today.
- `ruleset_reader`: an account with `?campaign=` reads with its seat's campaign (403 `NO_SEAT` without one there,
  unless it is an organiser, which reads as an organiser does today); without `campaign`, `Reader(principal, None)`.
- `/api/events?campaign=<id>`: `Viewer.of(principal, seat)` where an account's seat is `for_account(…, campaign)`
  (None without `campaign` or without a seat there); `Viewer` gains `login_hash: str | None = None`.
- `Tables` gains `account(account_id: str) -> Account | None` and `login_alive(token_hash: str) -> bool`
  (`StoredTables` reads storage).
- `EventBus.may_see`: an account viewer sees nothing once its login is gone or its account is disabled; its organiser
  right is the account's (as it is now); a `table` event only at its viewer's seat's campaign; the branch "the owner,
  seated at every table" only for `viewer.principal.owner`.
- `GET /api/me[?campaign=]` adds `"account": {id, username, display_name, language, organiser} | null`; for an
  account, `"seat"` is its live seat at `campaign` (same shape as today), and `"keepable_seat": {id, name} | null`
  (Task C5).
- `PUT …/seats/{seat_id}` with `organiser` on a seat with an `account_id` → 422 "Give an account organiser rights
  on the Players page."; the owner check reads `principal.owner`.

- [ ] **Step 1: Failing tests**
  - `tests/web/test_account_seats.py`: `test_table_seat_finds_the_accounts_seat` (account with a seat at A: `GET
    /api/campaigns/A/seats` 200; at B 403 "You have no seat at this table."); `test_host_and_actor_seats_for_accounts`
    (an account seat made host passes `HostSeat`; an observer's fails `ActorSeat`); `test_old_seat_tokens_still_work`
    (a token seat with no account: every probe of `tests/web/test_seats_identity.py` as before);
    `test_me_for_an_account` (`/api/me?campaign=A` → `account.username == "ana"`, `seat.campaign_id == "A"`);
    `test_account_reads_rulesets_with_its_table` (house rules of A with `?campaign=A`; 403 for B).
  - `tests/web/test_events_accounts.py`: `test_account_stream_sees_only_its_own_table` (account seated at A,
    stream `?campaign=A`: a `table` event of A arrives, one of B doesn't; stream without `campaign`: neither);
    `test_ended_login_stream_gets_no_more_events` (`storage.login_sessions.end_all(account)` while the stream is
    open: the next event of A doesn't arrive); `test_account_presence_is_its_seat` (`present(A)` holds the account's seat id while it listens).
- [ ] **Step 2: Run** `uv run pytest tests/web/test_account_seats.py tests/web/test_events_accounts.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest tests/web -q` → PASS, `tests/web/test_fourth_wall_per_seat.py` included.
- [ ] **Step 5: Commit** `Seats: an account's seat at each table, and its event stream at that table only (players and tavern Task C3)`.

### Task C4: Login, logout, sessions, password, links

**Files:**
- Create: `src/delve/web/routes/accounts.py`, `tests/web/test_login_api.py`
- Modify: `src/delve/web/app.py` (router), `tests/web/conftest.py` (helpers below)

**Interfaces** (all JSON; refusals `{"error": …}`):
- `POST /api/login` `{username, password}` → 200 `{"account": <me's account>}` and `Set-Cookie: delve_session=…;
  HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000` (plus `Secure` when `came_over_https`); 401 `"Wrong username or
  password."` for every refusal; 429 `"Too many tries: wait 15 minutes."`.
- Throttle (`LoginThrottle` in `routes/accounts.py`, its `clock = time.monotonic` patched in tests, state on
  `app.state.login_throttle`): `PER_USERNAME = 5`, `PER_ADDRESS = 20`, `WINDOW_S = 15 * 60`, `WAIT_S = 15 * 60`; a
  failure counts against the folded username (valid or not, known or not) and `client_address`; a success clears
  the username's count. Checked before the password is.
- `POST /api/logout` → 204, ends this login, clears the cookie (204 without one too).
- `GET /api/account/sessions` → `[{id, device, last_used_at, current}]`; `DELETE /api/account/sessions/{id}` → 204
  (404 for another account's); `POST /api/account/sessions/end-all` → 204, ends every login of the account, this one
  included, and clears the cookie.
- `PUT /api/account/password` `{old, new}` → 204, other logins ended (`logins.change_password`); 403 for a wrong old
  password (counts as a failed login for the throttle); 422 for a short new one.
- `GET /api/account-links/{token}` → `{username, kind}`; 404 `"This link doesn't work: ask for a new one."`.
- `POST /api/account-links/{token}` `{password}` → 200 `{"account": …}`, logged in (a new `delve_session`), every
  older login ended.
- `GET /api/account/tables` (account only, 403 otherwise) → `[{campaign_id, name, module_title, role, seat_id,
  last_played_at, session_number, banner}]` for its live seats, newest play first; `last_played_at` is the `at` of
  the campaign's newest story entry (null for none); `session_number` the campaign state's `session` (its last
  session); `banner` is whether `GET …/banner` has one.
- The routes under `/api/account/` answer 403 `"Log in to an account first."` to the owner and to seat tokens.
- `tests/web/conftest.py`: `PASSWORD = "correct horse battery"`; `def make_account(storage, username="ana", *,
  organiser=False) -> Account`; `def log_in(client, username="ana", password=PASSWORD) -> None`; a fixture `player`
  (the `lan` client logged in as `ana`).

- [ ] **Step 1: Failing tests** (`tests/web/test_login_api.py`): `test_login_sets_the_session_cookie` (flags exactly:
  HttpOnly, SameSite=Lax, Path=/, no Secure over http); `test_secure_only_from_a_https_proxy_here`;
  `test_login_any_case`; `test_wrong_and_unknown_say_the_same` (same status and body for an unknown username and a
  wrong password); `test_throttle_per_username` (5 failures → the 6th, with the right password, 429; at +15 min
  200); `test_throttle_per_address` (20 failures over 20 usernames from one forwarded address → 429 for a 21st
  username; another address unaffected); `test_throttle_unknown_usernames_too`; `test_logout_ends_the_session`;
  `test_end_all_logs_out_everywhere`; `test_password_change_ends_other_sessions`; `test_set_password_link`
  (made by `make_link`: `GET` names the user; `POST` logs in; a second `POST` 404); `test_link_expires_after_24_hours`;
  `test_no_password_in_answers_or_logs` (caplog and every response body of this file hold no password);
  `test_my_tables` (two seats at two campaigns, one left → one listed with its role).
- [ ] **Step 2: Run** `uv run pytest tests/web/test_login_api.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Accounts: log in, log out, log out everywhere, change the password, one-time links (players and tavern Task C4)`.

### Task C5: Joining by invite with an account, and keeping an old seat

**Files:**
- Modify: `src/delve/web/routes/join.py`, `src/delve/web/routes/seats.py`, `tests/web/test_join_api.py`, and the joins
  in `tests/e2e/test_a_faithful_book.py`, `test_a_journey.py`, `test_a_novel.py`, `test_a_table_of_three.py`,
  `test_read_a_world_map.py`

**Interfaces:**
- `GET /api/join/{token}` adds `"you": {account_id, display_name, seat_id} | null` (null unless the caller is an
  account; `seat_id` its live seat there or null).
- `POST /api/join/{token}` `{role: "player" | "observer", name?: str}`: an account only (401 `NEEDS_ACCOUNT = "Log
  in or make an account to join."` for anyone else, the owner included); the seat gets `account_id`, the name
  `name` or the profile's display name (made unique as today), the profile's language; no `delve_seat` cookie. An
  account with a live seat there → 200 with that seat (no second seat; an `IntegrityError` race → the existing one).
  201 for a new one: `{"seat", "campaign_id"}`.
- `POST /api/join/{token}/account` `{username, password, display_name, language, role}` → 201 `{"seat",
  "campaign_id", "account"}`: makes the account (409 "That username is taken."), logs it in (`delve_session`) and
  seats it, one transaction for the account and the seat.
- Both count against the join limit (`JOINS_PER_MINUTE = 10`), keyed by `client_address`.
- `POST /api/campaigns/{campaign_id}/seats/keep` (account only): the request's `delve_seat` seat, live, of that
  campaign, with no account and not the owner seat, becomes the account's; clears `delve_seat`; 200 `seat_json`.
  409 "You have a seat at this table already." when the account has one there; 404 when there is no such seat.
  `/api/me?campaign=` reports it as `keepable_seat`.
- The set-password and reset links' origin: `def link_origin(request) -> str`, factored out of `invite_json` (the
  LAN address when `is_this_machine`, else the request's base URL), used by `invite_json` and Task C6.

- [ ] **Step 1: Failing tests** (`tests/web/test_join_api.py`; the old name/role tests are rewritten for accounts):
  `test_join_needs_an_account` (no session → 401 "Log in or make an account to join."; the owner from this machine →
  401 too); `test_join_as_a_logged_in_account` (seat has `account_id`, name = display name, language = profile's,
  no `delve_seat` cookie); `test_join_twice_keeps_one_seat` (two POSTs → one live seat, same id, second 200);
  `test_make_an_account_by_invite` (201, logged in, seated; `/api/me` is the account); `test_invite_needed_to_make_one`
  (a bad join token → 404, no account made); `test_taken_username_409`; `test_join_limit_by_forwarded_address`;
  `test_keep_this_seat` (an old token seat + an account session → kept, `account_id` set, cookie cleared, the old
  token no longer needed); `test_keep_refused_with_a_seat_already` (409); `test_rejoin_after_leaving` (leave, join
  again → a new live seat).
- [ ] **Step 2: Run** `uv run pytest tests/web/test_join_api.py -q` → FAIL.
- [ ] **Step 3: Implement**; change the e2e tests' `POST /api/join/{token}` calls to `/account` with usernames
  (`ana`, `cy`, …) and `PASSWORD`.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS (the `tests/e2e` joins included).
- [ ] **Step 5: Commit** `Join: every invite asks for an account; keep this seat (players and tavern Task C5)`.

### Task C6: The organiser's Players API

**Files:**
- Create: `src/delve/web/routes/players.py`, `tests/web/test_players_api.py`
- Modify: `src/delve/web/app.py`

**Interfaces** (`Organiser` unless marked `Owner`):
- `GET /api/accounts` → `[{id, username, display_name, organiser, disabled, has_password, created_at, tables}]`
  (`tables`: its live seats' count), oldest first.
- `POST /api/accounts` `{username, display_name?, language?}` → 201 `{"account", "link": {"url", "expires_at"}}`:
  no password; the link is a `set-password` link at `<link_origin>/account/link/<token>`.
- `POST /api/accounts/{id}/reset-link` → `{"url", "expires_at"}` (`reset-password`; the old unused link stops).
- `PUT /api/accounts/{id}` `{disabled?: bool, organiser?: bool}`: `organiser` is the owner's alone (403
  `"Only the owner of this Delve makes organisers."` otherwise); disabling an organiser account is the owner's alone
  too; nobody disables their own account (422); disabling ends its logins (`logins.disable`).
- Each change publishes `accounts` (scope `organisers`).
- A player account (no organiser) gets 403 on every route here.

- [ ] **Step 1: Failing tests** (`tests/web/test_players_api.py`): `test_list_needs_an_organiser` (player account 403,
  seat token 403, organiser account 200, owner 200); `test_add_gives_a_set_password_link` (the link's `POST` sets the
  password and logs in); `test_reset_link_replaces_the_old`; `test_disable_ends_logins_and_login`
  (disabled → its open session 401, login 401); `test_only_the_owner_grants_organiser`;
  `test_only_the_owner_disables_an_organiser`; `test_no_password_hash_in_the_list`.
- [ ] **Step 2: Run** `uv run pytest tests/web/test_players_api.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make ci` → green.
- [ ] **Step 5: Commit** `Players: organisers add accounts, make reset links, disable and enable them (players and tavern Task C6)`.

---

## D. Profiles backend

**Owns:** `src/delve/play/profiles.py`, `src/delve/play/avatars.py`, `src/delve/web/routes/profiles.py`,
`src/delve/web/guard.py` (the avatar upload), `src/delve/web/routes/seats.py` (`seat_json`'s `profile`),
`src/delve/web/app.py` (router), `tests/play/test_profiles.py`, `tests/play/test_avatars.py`,
`tests/web/test_profiles_api.py`, `tests/web/test_guard.py` (avatar cases), `tests/fixtures/avatars.py`.

### Task D1: Profile fields, validation and the privacy check

**Files:**
- Create: `src/delve/play/profiles.py`, `tests/play/test_profiles.py`

**Interfaces:**
- `NAME_LENGTH = 40`, `PRONOUNS_LENGTH = 40`, `TEXT_LENGTH = 500`; `LANGUAGE = re.compile(r"[a-z]{2,3}")`.
- `def updated(profile: Profile, changes: dict[str, Any]) -> Profile`: the keys `display_name`, `pronouns`,
  `avatar_emblem`, `colour`, `language`, `about`, `host_note`, `time_zone`, each optional; unknown keys refused.
  Texts are stripped; control characters other than `\n` removed; display name 1–40 ("A display name has 1 to 40
  characters."); `avatar_emblem` in `EMBLEMS` (choosing one clears `avatar_sha`); `colour` in `COLOURS`;
  `language` a 2–3 letter code; `time_zone` null or a `zoneinfo` key (`ZoneInfo(key)` loads). `PlayError` for each.
- `@dataclass(frozen=True) class ProfileViewer: account_id: str | None; campaigns: frozenset[str]; hosting:
  frozenset[str]; organiser: bool` (campaigns where the viewer has a live seat; those where it is host or cohost).
- `def viewer_of_seat(storage, seat: Seat, *, organiser: bool) -> ProfileViewer`;
  `def viewer_of_account(storage, account: Account) -> ProfileViewer`;
  `def viewer_of_owner(storage) -> ProfileViewer` (every campaign; hosting where the owner seat is host or cohost).
- `def summary(account: Account) -> dict` → `{account_id, display_name, pronouns, avatar, colour}` with `avatar`
  `{"emblem": name}` or `{"picture": sha[:12]}` (the picture wins).
- `def card(storage, account_id: str, viewer: ProfileViewer) -> dict | None`: None unless the viewer is the account,
  an organiser, or shares a campaign with one of the account's live seats; `summary` plus `about`; plus `host_note`
  and `time_zone` when the viewer hosts a campaign where the account has a live seat; the account itself gets every
  field and `language`.

- [ ] **Step 1: Failing tests**: `test_profile_validation` (each limit above, at and past it); `test_emblem_clears_picture`;
  `test_unknown_key_refused`; `test_time_zone_known_or_null` (`Europe/Brussels` kept, `Mars/Olympus` refused);
  `test_card_needs_a_shared_table` (Ana at A, Bo at B: Bo's card for Ana → None; Cy at A → Ana's card);
  `test_host_sees_note_and_time_zone` (A's host sees them; a player at A doesn't; an organiser not hosting doesn't);
  `test_own_card_has_everything`.
- [ ] **Step 2: Run** `uv run pytest tests/play/test_profiles.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Profiles: the fields, their limits, and who may read them (players and tavern Task D1)`.

### Task D2: The avatar picture

**Files:**
- Create: `src/delve/play/avatars.py`, `tests/play/test_avatars.py`, `tests/fixtures/avatars.py` (Pillow-made test
  pictures: a 600×400 PNG, an EXIF-rotated JPEG, a 1×20000 PNG, a 2-frame WebP, a PNG header with a huge declared size)

**Interfaces:**
- `AVATAR_TYPES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}`, `AVATAR_LIMIT = 2 * 1024 * 1024`,
  `AVATAR_SIZE = 256`, `AVATAR_MAX_PIXELS = 16_000_000` (was 40 million until Clara's final audit).
- `class AvatarRefused(PlayError)` with `status: int` (400 or 422).
- `def square_avatar(data: bytes, media_type: str) -> bytes`: opens with Pillow; its format must be the type's
  (400 "That picture isn't a PNG/JPEG/WebP."); `width * height` over `AVATAR_MAX_PIXELS` → 422 "That picture is too
  large: at most 16 million pixels." (checked before decoding); first frame only; `ImageOps.exif_transpose`;
  `ImageOps.fit(…, (256, 256), centering=(0.5, 0.5))`; RGB(A) kept; returns WebP (quality 85), no metadata.

- [ ] **Step 1: Failing tests**: `test_avatar_is_256_square_webp`; `test_avatar_exif_rotated_upright` (a portrait
  photo stored landscape with orientation 6 → the result's top row is the photo's top); `test_avatar_strip_is_centre_cropped`;
  `test_avatar_first_frame_only`; `test_avatar_type_mismatch_is_400` (PNG bytes as `image/jpeg`);
  `test_avatar_pixel_bomb_is_422`; `test_avatar_has_no_metadata` (no EXIF in the output).
- [ ] **Step 2: Run** `uv run pytest tests/play/test_avatars.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Profiles: an uploaded avatar, upright, cropped square to 256 px (players and tavern Task D2)`.

### Task D3: The profile routes, and profiles in the seat list

**Files:**
- Create: `src/delve/web/routes/profiles.py`, `tests/web/test_profiles_api.py`
- Modify: `src/delve/web/guard.py`, `src/delve/web/routes/seats.py`, `src/delve/web/app.py`, `tests/web/test_guard.py`

**Interfaces:**
- `guard.AVATAR_PATH = "/api/account/avatar"`: a POST there must be one of `AVATAR_TYPES` (415 "send an avatar as
  one of image/jpeg, image/png, image/webp") of at most `AVATAR_LIMIT` (413, on the declared length; the route
  counts the bytes too). The fifth raw-body exception to the JSON rule.
- `GET /api/account/profile` (account only) → the own card. `PUT /api/account/profile` (JSON, the keys of
  `updated`) → the own card; publishes `seats` for each campaign of its live seats.
- `POST /api/account/avatar` (raw body) → the own card; stores `square_avatar` in the blob store (`image/webp`) and
  sets `avatar_sha`; 400/422 as `AvatarRefused`; nothing stored on a refusal. `DELETE /api/account/avatar` → back to
  the emblem.
- `GET /api/profiles/{account_id}` → `card` for the caller's `ProfileViewer` (an account, a seat token, the owner);
  404 `"No such player."` when `card` is None, so a stranger can't tell an account exists.
- `GET /api/profiles/{account_id}/avatar` → the picture's bytes, `image/webp`, `X-Content-Type-Options: nosniff`,
  `Cache-Control: private, max-age=86400`, under the same check (404 otherwise, or without a picture).
- `seat_json` gains `"profile": summary(account) | null` (null for a seat without an account, the owner's included).
- No route lists accounts to a player (`GET /api/accounts` stays the organisers').

- [ ] **Step 1: Failing tests** (`tests/web/test_profiles_api.py`, `tests/web/test_guard.py`):
  `test_put_profile_round_trip`; `test_profile_change_tells_the_tables` (a `seats` event at each of its campaigns);
  `test_avatar_upload` (the fixture PNG → card's avatar `{"picture": …}`, `GET …/avatar` 200 `image/webp`
  256×256 with nosniff); `test_avatar_wrong_type_415`, `test_avatar_too_large_413` (2 MB + 1 declared);
  `test_avatar_bytes_counted` (an undeclared 2 MB + 1 body → 413); `test_avatar_refusal_stores_nothing` (no new
  blob); `test_profile_of_a_stranger_is_404` (and its avatar); `test_seat_list_carries_profiles` (account seat →
  `profile.display_name`; token seat → null); `test_host_reads_the_note` / `test_player_does_not_read_the_note`;
  `test_seat_token_reads_its_tables_profiles`.
- [ ] **Step 2: Run** `uv run pytest tests/web/test_profiles_api.py tests/web/test_guard.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make ci` → green.
- [ ] **Step 5: Commit** `Profiles: read and change a profile, upload an avatar, profiles in the seat list (players and tavern Task D3)`.

---

## E. Account web pages

**Owns:** `web/src/account/` (new: `api.ts`, `Login.tsx`, `SetPassword.tsx`, `MyTables.tsx`, `AccountSection.tsx`,
`Players.tsx`, `KeepSeat.tsx`, `device.ts`, `account.css`, and their tests), `web/src/App.tsx`, `web/src/App.test.tsx`,
`web/src/api.ts`, `web/src/components/TokenGate.tsx`, `web/src/components/Nav.tsx`, `web/src/components/Nav.test.tsx`,
`web/src/routes/Join.tsx`, `web/src/routes/Join.test.tsx`, `web/src/routes/Preferences.tsx`,
`web/src/routes/Preferences.test.tsx`. E edits nothing under `web/src/play/` (F's, then G's).

### Task E1: The account API client and the login page

**Files:**
- Create: `web/src/account/api.ts`, `web/src/account/Login.tsx`, `web/src/account/Login.test.tsx`,
  `web/src/account/SetPassword.tsx`, `web/src/account/SetPassword.test.tsx`, `web/src/account/account.css`
- Modify: `web/src/App.tsx`, `web/src/components/TokenGate.tsx`, `web/src/App.test.tsx`

**Interfaces:**
- `web/src/account/api.ts`: `type Account = {id; username; display_name; language; organiser}`;
  `interface Me` (today's `Me` plus `account: Account | null`, `keepable_seat: {id; name} | null`);
  `getMe(campaign?: string): Promise<Me>`; `logIn(username, password): Promise<Account>`; `logOut()`;
  `getSessions()`, `endSession(id)`, `endAllSessions()`, `changePassword(old, next)`; `getLink(token)`,
  `useLink(token, password)`; `getMyTables()`; `joinAsAccount(token, {role, name?})`;
  `joinWithNewAccount(token, {username, password, display_name, language, role})`; `keepSeat(campaignId)`;
  `listAccounts()`, `addAccount(…)`, `resetLink(id)`, `changeAccount(id, {disabled?, organiser?})`; `accountKeys`.
  `App.tsx` imports `getMe` from here.
- `Login`: shown in place of the app on any 401 (the old gate's place): `login-username`, `login-password`,
  `login-submit`; the server's error in `role="alert"`; on success reload. Below, a closed disclosure
  "Have the owner's token?" (`login-token`) holding the old token field (`TokenGate`'s form, kept for the owner's
  other devices).
- `/account/link/:token` (outside the app, as `/join/:token`): `SetPassword` with `link-password`,
  `link-password-again`, `link-submit`; on success to `/`.
- i18n: `login.title` "Log in to Delve", `login.username`, `login.password`, `login.submit` "Log in",
  `login.ownerToken` "Have the owner's token?", `link.title` "Choose your password", `link.again` "Again",
  `link.differ` "The passwords differ.", `link.gone` (and the `nl` of each).

- [ ] **Step 1: Failing tests**: `Login.test.tsx` "logs in and reloads", "shows the server's refusal", "keeps the
  owner token"; `SetPassword.test.tsx` "sets the password", "refuses two different passwords", "says a used link
  doesn't work"; `App.test.tsx` "a 401 shows the login page, not the token page".
- [ ] **Step 2: Run** `cd web && npx vitest run src/account src/App.test.tsx` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Web: the login page in place of "Open the link Delve printed" (players and tavern Task E1)`.

### Task E2: The join page with accounts

**Files:**
- Modify: `web/src/routes/Join.tsx`, `web/src/routes/Join.test.tsx`

**Interfaces:**
- Not logged in (`link.you === null`): two tabs, **Make an account** (default; `join-username`, `join-password`,
  `join-name` as display name, `join-language` with the other-code field as today, the role radios, `join-submit`) and
  **Log in** (`join-login-username`, `join-login-password`, `join-login-submit`, then the role step).
- Logged in with no seat: the role radios, an optional name (`join-name`, the display name as placeholder),
  `join-submit`. With a seat already: straight to `/play/<campaign>`.
- After joining as a player: `PickCharacters`, unchanged.
- The join calls come from `account/api.ts`; `Join.tsx` still imports `getJoinLink`, `getSeats`, `claimCharacter`,
  `act` from `play/api.ts` (reads, no edits).
- i18n: `join.makeAccount`, `join.logIn`, `join.username`, `join.password`, `join.passwordHint` "At least 10
  characters", `join.displayName`.

- [ ] **Step 1: Failing tests** (`Join.test.tsx`): "makes an account and seats it", "logs in, then joins",
  "an account with a seat goes straight to the table", "shows a taken username", "keeps the other language code".
- [ ] **Step 2: Run** `cd web && npx vitest run src/routes/Join` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Web: the join page asks to log in or make an account (players and tavern Task E2)`.

### Task E3: My tables, a player's app, keep this seat

**Files:**
- Create: `web/src/account/MyTables.tsx`, `web/src/account/MyTables.test.tsx`, `web/src/account/KeepSeat.tsx`,
  `web/src/account/KeepSeat.test.tsx`
- Modify: `web/src/App.tsx`, `web/src/api.ts`, `web/src/components/Nav.tsx`, `web/src/App.test.tsx`,
  `web/src/components/Nav.test.tsx`

**Interfaces:**
- Route `/tables` (`MyTables`): a card per table (`my-table-<campaign id>`) with its banner
  (`/api/campaigns/{id}/banner` when `banner`), name, module, role, its last session ("Session 3, played 2 days
  ago"), and **Play**
  (`my-table-play-<id>` → `/play/<id>`); none → `tables.none` "You have no table yet: open an invite link.".
- An account that isn't an organiser: `/` → `/tables`; it may open `/tables`, `/play/:id`, `/preferences`,
  `/rulesets/*`; anything else → `/tables`. Its nav: My tables, Preferences, Log out (`nav-logout`). An organiser
  account has today's nav plus My tables and Log out. A seat token's browser keeps today's rule (its own table).
- The interface language of an account is `me.account.language`.
- `sharedEvents` (`web/src/api.ts`) opens `/api/events?campaign=<id>` on `/play/:id` for an account; an account
  listens nowhere else (`EventsContext` gets `notListening`).
- `KeepSeat`: on `/play/:id`, when `getMe(id).keepable_seat` is set, a notice above the screen (rendered by the
  `Shell`): "This browser has a seat here from before accounts: {name}." with **Keep this seat** (`keep-seat`).
- i18n: `tables.title` "My tables", `tables.play` "Play", `tables.lastPlayed`, `tables.none`, `nav.myTables`,
  `nav.logout` "Log out", `keepSeat.text`, `keepSeat.keep`.

- [ ] **Step 1: Failing tests**: `MyTables.test.tsx` "lists the tables with Play", "says when there are none";
  `App.test.tsx` "a player account lands on My tables", "a player account can't open Modules", "an account's stream
  names its campaign"; `Nav.test.tsx` "a player's nav"; `KeepSeat.test.tsx` "keeps the old seat".
- [ ] **Step 2: Run** `cd web && npx vitest run src/account src/App.test.tsx src/components/Nav` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Web: My tables, a player's own app, and keep this seat (players and tavern Task E3)`.

### Task E4: Preferences for everyone: Account; the Players page for organisers

**Files:**
- Create: `web/src/account/AccountSection.tsx`, `web/src/account/AccountSection.test.tsx`,
  `web/src/account/Players.tsx`, `web/src/account/Players.test.tsx`, `web/src/account/device.ts`,
  `web/src/account/device.test.ts`
- Modify: `web/src/routes/Preferences.tsx`, `web/src/routes/Preferences.test.tsx`, `web/src/App.tsx` (route)

**Interfaces:**
- `Preferences` sections in this order: Profile (an empty slot `<section id="profile">` that G fills), Account
  (accounts only), Look, Did you know, then the organiser sections: backends (organisers), Connections (the owner
  only), Players (organisers: a link to `/preferences/players`). A player account never asks for
  `/api/preferences` or `/api/backends`.
- `AccountSection`: change the password (`account-old`, `account-new`, `account-new-again`, `account-password-save`;
  "Your other devices are logged out."), the logins list (`account-session-<id>`: `deviceLabel(device)`, last used,
  "This device"; **Log out** per row), **Log out everywhere** (`account-end-all`, after a confirm dialog), and
  **Log out** (`account-logout`).
- `device.ts`: `deviceLabel(userAgent: string): string` → "Firefox on Linux", "Safari on iPhone", "Chrome on
  Android", "Edge on Windows", or "A browser".
- `/preferences/players` (`Players`, organisers): the accounts table (username, display name, tables, organiser,
  disabled); **Add a player** (`players-add`: username, display name, language → shows the set-password link with a
  Copy button and "Valid for 24 hours, once."); per row **Reset link**, **Disable**/**Enable**, and for the owner
  **Make organiser**/**Withdraw organiser**.
- i18n: `account.title` "Account", `account.password`, `account.sessions` "Where you're logged in",
  `account.thisDevice`, `account.endAll` "Log out everywhere", `account.logout`, `players.title` "Players",
  `players.add` "Add a player", `players.link`, `players.linkHint`, `players.reset`, `players.disable`,
  `players.enable`, `players.makeOrganiser`, `players.withdrawOrganiser`.

- [ ] **Step 1: Failing tests**: `Preferences.test.tsx` "a player sees Profile, Account, Look and Did you know only"
  (no backends, no Connections, no Players, and no request to `/api/preferences`), "the owner sees every section";
  `AccountSection.test.tsx` "changes the password", "lists the logins and logs one out", "logs out everywhere after
  confirming"; `Players.test.tsx` "adds a player and shows the link", "only the owner sees Make organiser";
  `device.test.ts` (each label above).
- [ ] **Step 2: Run** `cd web && npx vitest run src/account src/routes/Preferences` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make ci` → green.
- [ ] **Step 5: Commit** `Web: Account in Preferences, the Players page, organiser sections hidden from players (players and tavern Task E4)`.

---

## F. Tavern

**Owns:** `src/delve/play/pregame.py`, `src/delve/web/routes/play.py` (`play/state`'s `pregame`),
`tests/play/test_pregame.py`, `tests/web/test_pregame_api.py`, `web/src/play/Tavern.tsx`, `web/src/play/Tavern.test.tsx`,
`web/src/play/useTavern.ts`, `web/src/play/useTavern.test.ts`, `web/src/play/tavern.css`, `web/src/play/TalkPanel.tsx`,
`web/src/play/TalkPanel.test.tsx`, `web/src/play/Composer.tsx`, `web/src/play/Composer.test.tsx`,
`web/src/play/api.ts`, `web/src/routes/Play.tsx`, `web/src/play/Play.test.tsx`. F needs no account: it runs on
today's seats.

### Task F1: The pregame

**Files:**
- Create: `src/delve/play/pregame.py`, `tests/play/test_pregame.py`, `tests/web/test_pregame_api.py`
- Modify: `src/delve/web/routes/play.py`

**Interfaces:**
- `PAGE = 200`; `def in_pregame(storage: Storage, campaign_id: str) -> bool`: False while a beat is open or running
  (`storage.beats.current`); otherwise True when, reading the story back from its end `PAGE` entries at a time, a
  `recap` entry (the session's end) comes before any `player_act`, or the story has no `player_act`.
- `GET /api/campaigns/{id}/play/state` gains `"pregame": bool`.

- [ ] **Step 1: Failing tests**: `test_new_campaign_is_pregame`; `test_open_beat_is_not_pregame`;
  `test_after_an_act_not_pregame`; `test_after_the_recap_pregame_again` (acts, then a `recap` entry → True);
  `test_long_story_reads_back_by_pages` (450 entries, the act at seq 10, the recap at seq 400 → True);
  `tests/web/test_pregame_api.py::test_play_state_says_pregame` (a seat's `play/state`).
- [ ] **Step 2: Run** `uv run pytest tests/play/test_pregame.py tests/web/test_pregame_api.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Play: play/state says when the table is in its pregame (players and tavern Task F1)`.

### Task F2: Table talk full screen

**Files:**
- Create: `web/src/play/Tavern.tsx`, `web/src/play/Tavern.test.tsx`, `web/src/play/useTavern.ts`,
  `web/src/play/useTavern.test.ts`, `web/src/play/tavern.css`
- Modify: `web/src/play/TalkPanel.tsx`, `web/src/play/TalkPanel.test.tsx`, `web/src/play/Composer.tsx`,
  `web/src/play/Composer.test.tsx`, `web/src/play/api.ts` (`PlayState.pregame: boolean`), `web/src/routes/Play.tsx`,
  `web/src/play/Play.test.tsx`

**Interfaces:**
- `useTavern(pregame: boolean | undefined, beatStatus: BeatStatus | null): {open: boolean; setOpen(open: boolean)}`:
  opens once, when the first `play/state` says `pregame`; closes once, when the beat first goes from none to `open`
  or `running` after that (the first act, or the host's Go); `setOpen` is the seat's own switch and holds until then
  and after.
- `TalkPanel` gains `onTavern?: () => void`: a **Tavern** button (`tavern-open`) in its header, on the desktop only
  (`usePhone()` false).
- `Tavern({entries, mySeatId, seats, typing, submitted, onBack})`: across the play screen's middle in place of the
  story (`data-testid="tavern"`), the seat indicators on top, table talk below with Ask the DM answers and
  translations as the side panel shows them (it renders `TalkPanel`'s list), **Back to the story** (`tavern-back`).
- `Composer` gains `tavern?: boolean`: Enter talks, the Act and Pass buttons are hidden, Ask the DM stays.
- On a phone nothing changes.
- i18n: `play.tavern` "Tavern" / "Taverne", `play.backToStory` "Back to the story" / "Terug naar het verhaal",
  `play.tavernEmpty` "Nobody has said anything yet. Say hello while the others arrive." (and `nl`).

- [ ] **Step 1: Failing tests**: `useTavern.test.ts` "opens in the pregame", "stays shut out of it", "closes when
  the first beat opens", "the seat's own switch holds", "doesn't close again at the next beat";
  `Tavern.test.tsx` "shows the talk, the seats and Back to the story"; `TalkPanel.test.tsx` "the Tavern button
  opens it", "no Tavern button on a phone"; `Composer.test.tsx` "in the tavern Enter talks and there is no Act";
  `Play.test.tsx` "the tavern takes the story's place in the pregame", "Back to the story".
- [ ] **Step 2: Run** `cd web && npx vitest run src/play src/routes` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make ci` → green.
- [ ] **Step 5: Commit** `Play: the tavern, table talk full screen, open in the pregame (players and tavern Task F2)`.

---

## G. Profiles web

**Owns:** `web/src/profile/` (new: `emblems.tsx`, `Avatar.tsx`, `ProfileCard.tsx`, `ProfileSection.tsx`, `api.ts`,
`localTime.ts`, `profile.css`, and their tests), and after F and E are merged: `web/src/play/TalkPanel.tsx`,
`web/src/play/Tavern.tsx`, `web/src/play/SeatIndicators.tsx`, `web/src/play/PartySidebar.tsx`,
`web/src/play/TablePanel.tsx`, `web/src/play/InvitePanel.tsx`, `web/src/play/api.ts` (the `Seat.profile` type; drop
the unused `joinTable`), `web/src/routes/Play.tsx`, `web/src/routes/Preferences.tsx` (the Profile slot),
`web/src/routes/Join.tsx` (the "you are" line), `web/src/routes/CampaignDetail.tsx` (Party tab's seats), and their tests.

### Task G1: The emblems and the avatar

**Files:**
- Create: `web/src/profile/emblems.tsx`, `web/src/profile/emblems.test.tsx`, `web/src/profile/Avatar.tsx`,
  `web/src/profile/Avatar.test.tsx`, `web/src/profile/api.ts`, `web/src/profile/profile.css`

**Interfaces:**
- `EMBLEMS = ["lion", "eagle", "stag", "boar", "wolf", "dragon", "tower", "key", "sword", "crown", "moon", "oak"]
  as const` (the server's `delve.domain.accounts.EMBLEMS`, same order); `Emblem({name, title})`: an inline SVG, a
  heater shield outline with the charge, `viewBox="0 0 64 64"`, `fill="currentColor"`, one path group each, no
  external reference.
- `COLOURS = { teal: "#2c7a6b", jade: "#62b9a5", gold: "#e0bc74", ember: "#e08a3c" }`.
- `type ProfileSummary = {account_id; display_name; pronouns; avatar: {emblem: string} | {picture: string}; colour}`;
  `getProfile(accountId)`, `getOwnProfile()`, `putProfile(changes)`, `uploadAvatar(file: File)` (raw body, the
  file's type), `removeAvatar()`; `profileKeys`.
- `Avatar({profile, size = 32, onClick?})`: the picture (`/api/profiles/<id>/avatar?v=<picture>`) or the emblem in
  the colour, round, with a ring in the colour; a seat without a profile gets a plain dot of the ink colour.
- No i18n keys but each emblem's name: `emblem.lion` "Lion" / "Leeuw", … (12 each).

- [ ] **Step 1: Failing tests**: `emblems.test.tsx` "has the twelve emblems, in the server's order", "each is an
  inline SVG with no href"; `Avatar.test.tsx` "shows the picture", "shows the emblem in the colour", "a seat without
  a profile".
- [ ] **Step 2: Run** `cd web && npx vitest run src/profile` → FAIL.
- [ ] **Step 3: Implement** (the twelve drawings: simple heraldic charges, one path each, in the style of a woodcut).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Web: twelve heraldic emblems and the avatar (players and tavern Task G1)`.

### Task G2: The profile page

**Files:**
- Create: `web/src/profile/ProfileSection.tsx`, `web/src/profile/ProfileSection.test.tsx`
- Modify: `web/src/routes/Preferences.tsx`, `web/src/routes/Preferences.test.tsx`

**Interfaces:**
- In Preferences' Profile slot, accounts only: display name (`profile-name`), pronouns (`profile-pronouns`), the
  avatar (the 12 emblems as radio buttons `profile-emblem-<name>`, **Upload a picture** `profile-upload`, accepting
  `image/png,image/jpeg,image/webp`, a client check of 2 MB with "At most 2 MB.", **Remove the picture**), colour
  (`profile-colour-<name>`), language, about me (`profile-about`, 500 with a counter), note for the host
  (`profile-note`, with "Only the hosts of your tables read this."), time zone (`profile-time-zone`, the browser's
  `Intl.supportedValuesOf("timeZone")` with "None"), **Save** (`profile-save`), and a preview `Avatar` with the name.
- i18n: `profile.title` "Profile", `profile.displayName`, `profile.pronouns`, `profile.avatar`, `profile.upload`,
  `profile.removePicture`, `profile.tooLarge`, `profile.colour`, `profile.colour.teal|jade|gold|ember`,
  `profile.about`, `profile.note`, `profile.noteHint`, `profile.timeZone`, `profile.noTimeZone`, `profile.saved`.

- [ ] **Step 1: Failing tests**: "saves the fields", "uploads a picture and shows it", "refuses a picture over 2 MB
  without sending it", "choosing an emblem removes the picture", "the owner has no Profile section".
- [ ] **Step 2: Run** `cd web && npx vitest run src/profile src/routes/Preferences` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Web: the profile page (players and tavern Task G2)`.

### Task G3: Faces at the table, and the profile card

**Files:**
- Create: `web/src/profile/ProfileCard.tsx`, `web/src/profile/ProfileCard.test.tsx`, `web/src/profile/localTime.ts`,
  `web/src/profile/localTime.test.ts`
- Modify: `web/src/play/api.ts`, `web/src/play/TalkPanel.tsx`, `web/src/play/Tavern.tsx`,
  `web/src/play/SeatIndicators.tsx`, `web/src/play/PartySidebar.tsx`, `web/src/play/TablePanel.tsx`,
  `web/src/play/InvitePanel.tsx`, `web/src/routes/Play.tsx`, `web/src/routes/Join.tsx`,
  `web/src/routes/CampaignDetail.tsx`, and the tests of each

**Interfaces:**
- `Seat` (web) gains `profile: ProfileSummary | null`.
- Table talk and the tavern: each line's `Avatar` and the colour's left bar, from the seat list by `seat_id` (a seat
  that left: the name alone).
- `SeatIndicators`, `TablePanel`'s seat list: the `Avatar` beside the name. `PartySidebar` gets `seats` and shows
  the player's `Avatar` beside each character that seat plays (never in place of the portrait).
- The campaign page's Party tab: a Seats list (name, role, `Avatar`), from `GET …/seats`.
- Join: "You are {name}" with the `Avatar` and "Not you? Log out" (`join-not-you`) when `link.you` is set.
- `InvitePanel`'s hint: "Whoever opens the link makes an account or logs in, then takes a seat."
- `ProfileCard({accountId, onClose})`: a click on any `Avatar` at the table opens it: name, pronouns, about me; for a
  host also the note for the host and "Their time: 21:40 (Europe/Brussels)" (`localTime(timeZone, now)`).
- `localTime(timeZone: string, now: Date, language: string): string` with `Intl.DateTimeFormat`.
- i18n: `card.pronouns`, `card.about`, `card.note`, `card.localTime` "Their time: {time} ({zone})",
  `join.youAre` "You are {name}", `join.notYou` "Not you? Log out", `invite.accountHint`, `campaign.seats` "Seats".

- [ ] **Step 1: Failing tests**: `TalkPanel.test.tsx` "a line shows its speaker's avatar and colour";
  `SeatIndicators.test.tsx` "avatars beside the names"; `PartySidebar.test.tsx` "the player's avatar beside the
  character, the portrait kept"; `ProfileCard.test.tsx` "a player sees name, pronouns, about", "a host also sees the
  note and the local time"; `localTime.test.ts` (Europe/Brussels at a fixed UTC instant); `Join.test.tsx` "says who
  you are"; `CampaignDetail.test.tsx` "the Party tab lists the seats".
- [ ] **Step 2: Run** `cd web && npx vitest run src/play src/profile src/routes` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `make ci` → green.
- [ ] **Step 5: Commit** `Web: players' faces in table talk, the seats, the party and the join page; the profile card (players and tavern Task G3)`.

---

## H. Two-browser e2e spec

**Owns:** `web/e2e/tavern.spec.ts` (new), `tests/e2e/fake_play_server.py` (a turn and its docstring), and the joins of
`web/e2e/table.spec.ts`, `rulesets.spec.ts`, `worldmap.spec.ts`, `x-novels.spec.ts`, `y-carry.spec.ts`,
`zz-faithful.spec.ts`, and the screenshots under `web/e2e/screenshots/`.

### Task H1: The existing specs join with accounts

**Files:** Modify the specs above.

- [ ] **Step 1:** Each page join (`table.spec.ts`: Ana, Cy) makes an account on the join page (usernames `ana`,
  `cy`; password `correct horse battery`); each API join (`rulesets.spec.ts`, `worldmap.spec.ts`, `x-novels.spec.ts`,
  `y-carry.spec.ts`, `zz-faithful.spec.ts`) becomes one `POST /api/join/{token}/account` with a username of its own
  (`eli`, …), still one request each (the join limit). A context that joined keeps its `delve_session` cookie as it
  kept `delve_seat`.
- [ ] **Step 2: Run** `make e2e-browser` → every existing spec PASS.
- [ ] **Step 3: Commit** `e2e: the specs join with accounts (players and tavern Task H1)`.

### Task H2: The tavern spec, in two browsers

**Files:**
- Create: `web/e2e/tavern.spec.ts`
- Modify: `tests/e2e/fake_play_server.py`, the comment of `web/e2e/zz-faithful.spec.ts` ("the fake's fourth beat")

**Order:** by file name it runs after `table.spec.ts` and before `thorough-conversion.spec.ts`. The fake's turns are
one queue for every campaign: `TURNS` gains, at index 2 (after the table's beat, before `FAITHFUL_TURNS[0]`), the
tavern's beat `[{"text": TAVERN_REPLY}]`, `TAVERN_REPLY = "The innkeeper sets down two mugs, and the fire crackles in
the hearth."`. No spec between `tavern.spec.ts` and `zz-faithful.spec.ts` plays a beat (check, and say so in the
docstring).

**The spec** (`test("an account joins by invite, sets a profile, talks in the tavern, plays, and finds its seat again")`):
1. The owner (`request`, this machine) makes a campaign "The Wayside Inn" on the crypt module (`POST /api/campaigns`,
   as `looks.spec.ts` does), a PC "Wren" (`POST /api/campaigns/{id}/characters`), and reads the invite's token.
2. Wren's player is outside: `browser.newContext({ extraHTTPHeaders: { "X-Forwarded-For": "203.0.113.24" } })` (a
   visitor through a proxy on this machine, as through the owner's tunnel). `/join/<token>` shows Make an account;
   username `wren.player`, password `correct horse battery`, display name "Mira", English, Play → picks Wren →
   `/play/<id>`. The tavern is open by itself (`tavern` visible, the story not).
3. Mira opens Preferences: pronouns "she/her", uploads an avatar (a 300×200 PNG made in the spec as a `Buffer`),
   colour `ember`, Save; `GET /api/profiles/<id>/avatar` in her context is 200. Back by My tables → Play.
4. The host's page (`page`, this machine) opens `/play/<id>`: its tavern is open too. The host says "Welcome to the
   Wayside Inn!" in the tavern; Mira sees it. Mira says "Glad to be here."; the host sees her line with her uploaded
   avatar (`img[src*="/api/profiles/"]`) and the ember bar. Screenshot `tavern-1280x800.png` (host).
5. Mira goes Back to the story and acts "Wren pushes open the inn's door."; the host's tavern closes by itself;
   both read `TAVERN_REPLY`.
6. Nothing of the owner's in Mira's context: `GET /api/campaigns` 403, `/api/preferences` 403, `/api/connections`
   403, `/api/campaigns/<id>/dm/log` 403, `/api/accounts` 403.
7. Mira logs out (Preferences → Account → Log out): the login page. Screenshot `login-1280x800.png`.
8. A fresh context (`X-Forwarded-For: 203.0.113.25`): `/` shows the login page; log in as `wren.player` → My tables
   lists "The Wayside Inn" (screenshot `my-tables-1280x800.png`) → Play → her line "Glad to be here." shows as hers
   ("You"), the composer acts for Wren, and the tavern is shut (no pregame).
9. The owner deletes the campaign (`DELETE /api/campaigns/<id>`, 204), so the later specs see what they saw before.

- [ ] **Step 1: Write the spec** and the fake's turn; run `make e2e-browser` → the new spec FAILS before G is
  merged, PASSES after.
- [ ] **Step 2: Run** `make e2e-browser` → every spec PASS; `uv run pytest tests/e2e -q` → PASS (the Python tests
  that share `fake_play_server.py`).
- [ ] **Step 3: Commit** `e2e: an account joins, talks in the tavern, plays and finds its seat again (players and tavern Task H2)`.

---

## S. Docs

**Owns:** `docs/glossary.md`, `docs/data-dictionary.md`, `docs/backlog.md`, `docs/progress.md`, `GUILD.md`.

### Task S1: Words, values, the backlog and the working rules

- [ ] **Step 1: Glossary** (`## People and roles`): **Account** ("A person's login on this Delve: a username and a
  password, made through an invite or by an organiser; it holds their profile and their seats at every table. An
  account is never the install's owner; it may be an organiser."), **Profile** ("What a player shows of themselves at
  their tables: display name, pronouns, avatar, colour, about me; the hosts also read their note and time zone. Never
  their character's portrait."), **Tavern** ("Table talk full screen, in place of the story: open by itself before
  an evening's first act."). **Seat** gains "An account's seat follows it to any device."; **Join link** "…gives
  whoever opens it, once logged in or with a new account, a seat…"; **Organiser** "…and only the owner can make a
  seat or an account one." Under "Words we avoid": "session" for a login (say "logged in", "Where you're logged
  in"); "user" in the UI (say player or account).
- [ ] **Step 2: Data dictionary** rows: `accounts.username`; `accounts.colour` (`teal`, `jade`, `gold`, `ember`);
  `accounts.avatar_emblem` (the 12); `accounts.avatar_sha`; `accounts.external_id` (reserved, null);
  `accounts.organiser`, `accounts.disabled_at`; `account_links.kind` (`set-password`, `reset-password`, 24 h, once);
  session cookie `delve_session` (flags as Global Constraints, `login_sessions.token_hash`, 30 days from last use);
  `seats.account_id`; `play/state`'s `pregame`; the `accounts` event; the seat JSON's `profile`. Amend
  `delve_seat`: "set by joins before accounts (migration `0020_accounts`); still accepted".
- [ ] **Step 3: Backlog**: Features 34 and Interface 4 struck through with "Done in players and tavern (2026-10-24)",
  as earlier done items are; `docs/progress.md` as the repo does for delivered work.
- [ ] **Step 4: GUILD.md**: the request rules gain the fifth raw-body exception (`POST /api/account/avatar`: PNG, JPEG
  or WebP, at most 2 MB, 415/413/400/422); a section `## Players and the tavern` covering: the identity chain and its
  order (`docs/identity.md`), "an account is never the owner", "no route reads a cookie but `delve.web.auth`",
  "`login_sessions`, never `sessions`, for logins", the throttle numbers, the account's event stream
  (`?campaign=`), `make_account`/`log_in`/`PASSWORD` in `tests/web/conftest.py` and the `fast_scrypt` fixture,
  profiles' privacy (`delve.play.profiles.card`), the tavern's `pregame`, and the e2e order: `tavern.spec.ts` after
  `table.spec.ts`, its fake turn at `TURNS[2]`, outside visitors by `X-Forwarded-For`, every join with an account.
- [ ] **Step 5: Run** `make ci` → green.
- [ ] **Step 6: Commit** `Docs: Account, Profile and Tavern; the values; Features 34 and Interface 4 done (players and tavern Task S1)`.
