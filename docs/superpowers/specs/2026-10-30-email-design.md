# Email: password resets, host mail and board replies

Delve sends email through a small provider layer, with Emailit as the first real provider and a log-only provider for
development and tests. Settled with the owner on 2026-10-30.

## Why

Delve sends no email today. A player who forgets their password asks the owner through "Forgot your password?" on
the login page (DEL-268, `POST /api/password-help`); the request waits on the Players page until an organiser makes a
reset link and hands it over by hand. Someone who signs up (DEL-156) waits for approval with no way to hear when it
comes. Hosts have no way to tell their table that Thursday is off, or to ask one player about their character, except
outside Delve. And a player who asks a question on the board has to keep coming back to see whether anyone answered.
The owner wants, in this order:

1. **Password resets by email**, through the "Forgot your password?" form that exists.
2. **"You're in" on approval** of a sign-up.
3. **Mail from hosts:** optionally on Skip or Move of the next session, and messages a host writes to the whole table
   or to some of its players.
4. **Board reply notifications**, for the topics a player chose to follow.

## Goals

- **A provider layer.** Delve code asks one interface to send a message; providers plug in behind it. Shipped
  providers: `log` (writes the message to Delve's log, sends nothing; the default, and what tests use) and `emailit`.
  Adding a provider later is one adapter, no change to the senders.
- **An optional, private address per account.**
  - Every account may have one email address, or none. Nobody but the account sees it: not other players, not hosts,
    not organisers, not the owner in the UI. Organisers see only whether an account has a confirmed address, so they
    know whether "Forgot your password?" works for that player.
  - **Typed-in addresses are confirmed** by a link sent to them before Delve sends anything else there. Until then the
    address is pending and receives nothing but the confirmation.
  - **Google's address is trusted as given** (owner's decision): an account that signs up or links with Google gets
    that address, confirmed, when it has none yet (and Google says the address is verified; builder: the claim is
    `email_verified`). A later Google login doesn't overwrite an address the player set or changed themselves, and
    doesn't bring back one they removed: only signing up and linking fill it (accounts linked before email got it
    once, by migration 0044).
  - The player changes or removes the address in Preferences. A change sends a new confirmation; the old address
    stays in use until the new one is confirmed. Builder's call whether to also tell the old address of the change.
- **Password reset by email, in the form that exists** (`web/src/account/Login.tsx`, `delve.web.routes.password_help`,
  `accounts.ask_for_reset`). One form, extended, not replaced (owner's decision):
  - **No real provider set:** it works exactly as today: the request goes to the owner's Players page.
  - **A provider set, and the account has a confirmed address:** Delve emails a reset link straight away (the same
    one-time link an organiser's Reset link makes, `accounts.make_link(..., "reset-password")`, `LINK_HOURS`, an older
    unused one stops working) and records no request to the owner.
  - **A provider set, no confirmed address:** the request goes to the owner, as today.
  - The player may type their username or their address. An address counts only when it is an account's confirmed
    address; one that matches nothing records nothing.
  - The answer reads the same in every case, so it doesn't reveal whether an account or an address exists (my
    wording, to refine: "If your account has a confirmed email address, a link is on its way; if not, the owner has
    your request."). The form's explanation ("Delve sends no mail…", `forgot.explain`) changes to match while a
    provider is set.
  - The existing per-caller throttle (`PER_ADDRESS`, `SignUpThrottle`) stays; add a per-account limit on reset emails
    so an inbox can't be flooded.
  - An owner's or organiser's account may reset itself by email like any other (`make_link`'s `by_owner` rule is
    about an organiser acting on someone else's account; the account asking for itself is not that).
  - A reset email is always sent; it has no unsubscribe link.
- **"You're in" on approval.**
  - The sign-up form (`delve.web.routes.sign_up`, DEL-156) gets an optional email field. Delve sends the confirmation
    link at once, so the player can confirm while they wait. A Google sign-up has its confirmed address already.
  - When the owner or an organiser approves the account, Delve emails "You're in" with a link to the login page, if
    the address is confirmed by then. Like a reset email, it is always sent and has no unsubscribe link.
  - A rejected sign-up gets no email (rejection is quiet today). The confirmation link of a rejected or deleted
    account stops working.
- **Mail on Skip and Move.**
  - The Skip and Move actions on the play screen (`delve.play.schedule.change_next`) get a "Tell the players by email"
    choice, off by default, with an optional line from the host.
  - The email names the table, what changed (skipped; or moved, with the new date and time in each recipient's own
    time zone, as the screens show it), and the host's line.
  - It goes to the table's seated players, co-hosts and host who have a confirmed address and haven't turned host mail
    off, except the host who made the change. Not to observers (my call; the owner's picture was "the players"). The
    owner's seat at every table counts only if the owner plays or hosts there.
  - A recipient with no time zone of their own gets the schedule's time zone, named in the email.
- **Hosts write to the table.**
  - On the play screen's host controls (`web/src/play/HostControls.tsx`; the campaign page is organisers' only, so a
    host who isn't an organiser never sees it), the host and co-hosts can write a message: a subject and plain text,
    to the whole table or to the people they tick.
  - Delve sends it from its own address, saying which host and which table it is from. The host never sees the
    recipients' addresses. Replies go to the host only if the host chooses that for this message ("Let them reply to
    my address"), using the host's confirmed address as `Reply-To`; otherwise the email says replies aren't read and
    to answer in Delve.
  - The form shows how many of the chosen people will get it (have a confirmed address and host mail on), not who
    doesn't.
  - A host can send a limited number of messages per table per day (builder's call on the number, something like 10),
    so Delve's sending account isn't used for spam.
- **Board reply notifications.**
  - Under the reply box and the new-topic form, an "Email me about replies" box. Ticking it follows that topic for
    this account; the topic's page lets them stop following it. Preferences has one switch that stops all of them.
  - One email on the first reply after the follower last read the topic, then nothing for that topic until they open it
    again (the board's read marks, `board_reads`, already record that). It names the zone and topic, who replied, a
    short plain-text excerpt of the reply, and a link to the first unread post.
  - Never for one's own posts. Never for a zone the follower can no longer read: check the board's rights
    (`delve.play.board_rights`) at send time, not when they followed.
  - Board replies are the only notification in this work. (The owner: "for the board, that's all for now.")
- **Each kind of mail can be turned off by the player** in Preferences: host mail and board replies, each its own
  switch. Every non-reset email ends with a link that turns that kind off in one click, without logging in, and carries
  a `List-Unsubscribe` header pointing at it.
- **In the recipient's language.** Each email is written in the recipient account's Delve language (en, nl, fr, de,
  lv), through the app's translations, like the rest of the interface. The words a host or a poster wrote aren't
  translated. Plain, readable emails: a text part and a simple HTML part with a light Delve header, no images loaded
  from elsewhere, no tracking.
- **Setting it up.**
  - Preferences → Connections (the owner's alone, like Replicate and Google login) gets an **Email** row: the provider
    (Log only, or Emailit), Emailit's API key (stored in the data dir's files like the other tokens, never shown again,
    only "set"), the **From** address (`Delve <noreply@example.org>`), and **Send a test email**, which sends to the
    owner's own confirmed address and answers in Delve's own words.
  - An `EMAILIT_API_KEY` in the environment wins over a saved key, as `REPLICATE_API_TOKEN` does.
  - A help topic for the owner (beside "Connecting Delve to other services") on setting up Emailit: make a Sending Only
    key restricted to the sending domain, add the domain and its DNS records (below), press Check DNS, and ask Emailit
    for production access.
  - While no real provider is set, everything that would email says so honestly: "Forgot your password?" goes to the
    owner as today, and the host's email choices aren't offered (or are offered disabled with the reason; builder's
    call which). Confirming needs a sent email, so the address field in Preferences and on sign-up shows only while a
    real provider is set (my call); addresses from Google are kept either way.

## Non-goals

- Bounce and complaint handling (Emailit's webhooks). Later work.
- An in-app note for players without an address, in place of the email they miss.
- Notifications other than board replies (new topics, mentions, session reminders, …).
- Digests, scheduled sending, attachments, templates kept at Emailit, open or click tracking.
- Emailing visitors or anyone without an account. Mailing lists or newsletters to all accounts.
- Logging in by email link.

## Anti-goals (a failure even if it works)

- **An address leaks:** to another player, a host (including through `Reply-To` or a `To` line listing several
  people: send one email per recipient), an organiser, an API answer, the events stream, or the log. The log-only
  provider logs a message's kind, recipient account and subject, and the body only when Delve runs in development.
  Builder's call on how to tell.
- **Mail goes to an address its owner never confirmed.**
- **A reset email tells someone whether an account or address exists.**
- **A thread or a host floods an inbox.**
- **Sending blocks a request or a beat.** A slow or failing provider must not slow posting a reply, skipping a session
  or the login page.
- **An email is lost silently.** One that fails is retried; one that keeps failing is recorded where the owner can
  see it.
- **An API key in a log, an answer or an error message.**

## Constraints and facts

### Emailit (from its documentation, 2026-10-30)

- `POST https://api.emailit.com/v2/emails`, `Authorization: Bearer <key>`, JSON body.
- Body fields used here: `from` (must be on a verified sending domain, `"Delve <noreply@example.org>"`), `to`,
  `subject`, `html`, `text`, `reply_to` (string or list), `headers` (object; for `List-Unsubscribe`), `meta` (string
  values, echoed in webhooks; useful later for bounces: put Delve's message id in it).
- `Idempotency-Key` header (up to 256 of letters, digits, `-`, `_`): a retry with the same key within 24 hours returns
  the first answer instead of sending again. Use Delve's own message id, so a retry after a timeout never sends twice.
- Answers: 200 with the email object (`id` `em_…`, `status` `accepted`); 400 validation (`validation_errors`); 401 bad
  key; 402 not enough credits; 403 `unverified_workspace_recipient` (the workspace is still in sandbox, which only
  sends to its members' own addresses) or domain not authorised for this key; 422 domain not verified; 429 rate limit
  with `retry_after`; 5xx. Retry 429 and 5xx (and timeouts) with backoff; don't retry the others. Record them for the
  owner in Delve's words.
- Limits: 2 emails per second per workspace; 100 a day on Pay as you go until the first credit purchase, then 5,000; 1
  credit per recipient. Delve's sending must pace itself to stay under 2 per second.
- New workspaces are in sandbox until Emailit grants production access. The owner's account is still being validated,
  so the work must be fully buildable and testable on the log-only provider.
- Domain verification needs three DNS records, all passing:
  - SPF: TXT at `emailit.<domain>`, `v=spf1 include:_spf.emailit.com ~all`;
  - DKIM: TXT at `emailit._domainkey.<domain>`, the `p=` key copied from Emailit's domain page;
  - Return path: MX at `emailit.<domain>`, exactly one, to `feedback-smtp.ffdc-1.emailit.com`.

  DMARC is checked but not required; the help topic recommends a `_dmarc.<domain>` TXT record (`v=DMARC1; p=none;`
  to start). Emailit doesn't verify a new domain by itself: press **Check DNS** after adding the records. On Pay as you
  go, a domain registered less than 30 days ago is also reviewed by hand.
- Sources: <https://emailit.com/docs/email-api/>, <https://emailit.com/docs/api-reference/emails/send/>,
  <https://emailit.com/docs/domains/verification/>.

### Delve

- Accounts: `delve.domain.accounts`, the `accounts` table. Google identities (`delve.play.identities`, migration 0030)
  already store the email Google gave, "shown, never matched"; an account's own address is a new, separate field,
  and identities are still matched by subject only.
- One-time links: `accounts.make_link` / `use_link`, `LINK_HOURS`; `/account/link/{token}`. Reuse them for reset.
  `make_link` drops an account's other unused links, so a confirmation link must not live among them (a reset would
  kill a pending confirmation and the other way round): give confirmation its own token, not a `make_link` kind.
  `make_link` also clears `reset_asked_at`, which is right: an emailed reset answers the request.
- Connections: `delve.web.routes.connections`, `delve.images.connections` (tokens in the data dir, `set`/`unset`, owner
  only, Test answers in Delve's own words). The Email row follows the same rules.
- Links in emails need Delve's public address. `link_origin(request)` (`delve.web.routes.join`) picks one from the
  request, which is wrong for an email triggered from this machine (it would point at a LAN address) or from a
  background task (no request). The work needs a configured public address for emails (e.g. on the Email connection,
  defaulting to the tunnel's name in `guard.allowed_hosts()` when there is exactly one). Builder's call on the shape.
- Background work runs as asyncio tasks started in `delve.web.app` (backup and library update loops are examples).
- Migrations: plain `ALTER TABLE` on referenced tables, never a batch rebuild of `accounts` or `campaigns` (a batch
  rebuild once cascaded characters away); take the next free number from master at the time.
- Every word in the UI and every email goes through the i18n dictionaries in all five languages
  (`web/src/i18n/*.json` for the web; the server needs its own source for email text, builder's call where).
- Help topics in `web/src/help/topics`, translated as the others are.
- Players and the owner reach Delve over a tunnel; the owner token works only on this machine.

## Decided shape

- **An outbox.** Senders don't call the provider. They write a message (kind, recipient account, language, subject,
  text, HTML, optional reply-to, idempotency key) to an outbox table in the same transaction as what caused it, and a
  background sender delivers it: paced to Emailit's 2 per second, retrying temporary failures with backoff for a while
  (builder's call, hours not days), then marking it failed with Delve's reason. The address is looked up when sending,
  so a message to an account whose address was removed or turned that kind off is dropped, not sent.
- **The owner sees the outbox's health** on the Email connection row: the last test, how many sent today, and the last
  few failures in Delve's words (no addresses shown; not the dropped ones), and how many wait. Builder's call how much.
- **Provider interface**, roughly: `send(message) -> accepted | temporary failure (retry after) | permanent failure
  (reason)`. The log provider always accepts. Tests use it. Once the owner switches email off (back to the log),
  mail left in the outbox fails as "not sent: email was switched off" rather than passing as sent; a test still goes
  to the log.

## Left to the builder

- Table and column names; whether the confirmation is a new link kind or its own table.
- The exact pages and forms (follow the existing screens and their tours and help: Preferences tabs, the login page,
  the Skip and Move dialogs, the campaign page, the board's reply box).
- Rate limit numbers for reset requests and host messages.
- Email layout, within: plain, readable, both text and HTML, in the recipient's language, a link to turn that kind
  off, no remote images.
- Whether "Forgot your password?" and host email choices are hidden or shown disabled while no provider is set.
- Splitting the work into tasks. A sensible order is the owner's: the layer, the outbox and the log provider; addresses
  and confirmation (Preferences, sign-up, Google); password reset in the existing form; "You're in" on approval;
  Emailit and the Connections row with its help topic; Skip and Move; host messages; board replies.
