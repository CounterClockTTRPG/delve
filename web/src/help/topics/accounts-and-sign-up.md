---
title: Accounts and sign-up
audience: owner
summary: Add players, make organisers, open sign-up, let people in and give them reset links.
screens: /preferences/players, /preferences
order: 2
related: install-and-first-run, connections, getting-in, invite-players
---
Every account of this Delve is on the Players page: open **Preferences**, the **Players** tab, then **Open Players**.
Organisers can use this page too; some actions are yours alone.

## Who can do what

- Players reach their own tables, the play screens, **Preferences** and the Rulesets.
- Organisers also start campaigns, look after modules and house rules, set the backends, and manage players'
  accounts here.
- Owners can do everything. Only an owner chooses **Make organiser** or **Make owner** (and **Withdraw
  organiser**, **Withdraw owner**), and only an owner disables or resets an organiser's or an owner's account. The
  last owner account stays an owner.

## Where accounts come from

- From an invite link: anyone who opens a table's invite link can make an account.
- From this page: fill in a **Username**, a **Display name** and a **Language**, then choose **Add a player**. Delve
  shows a link that sets the password. Send it to the player: it works once, within 24 hours.
- From sign-up: people ask for an account themselves (see below).
- From the command line: `uv run delve account add <username>` makes an account and asks for its password. Add
  `--organiser` or `--owner` for those rights.

## Sign-up with approval

Sign-up is off until you tick **Let people ask for an account**. While it is on, the login page offers **No account?
Ask for one**. Each new account waits under **Waiting for approval**, with the line its person wrote about who they
are. The menu shows how many wait.

- **Let in**: the account can log in from now on.
- **Turn away**: the account is deleted, and its username is free again.

Someone waiting who logs in through a table's invite link is let in by it. Each address may ask 3 times an hour, and
at most 20 sign-ups wait at once.

<figure><img src="/help/players-waiting.webp" alt="One sign-up under Waiting for approval, with its note, Let in ringed and Turn away beside it" width="984" height="170" loading="lazy"></figure>

## Forgotten passwords and problems

- **Forgot your password?** on the login page asks for a username or, while Delve sends email, an email address. An
  account with a confirmed address gets its reset link by email, at most 3 an hour; no request waits for you. Any
  other account's request waits here, under **Asked for a new password**, until you make its **Reset link** or
  dismiss it.
- **Reset link** makes a new set-password link for the account; its older unused link stops working. A reset also
  unlinks every Google account linked to it.
- **Disable** stops the account and logs it out everywhere; **Enable** brings it back. You can't disable your own
  account. Accounts are never deleted, except a sign-up you turn away.

## Google accounts

Once you set up Google login under [Connections](/help/connections), people can sign up and log in with Google. A
Google sign-up still waits for approval. Someone with an account can choose **Link your Google account** on their
**Profile** tab. Delve matches a Google account only to the account that linked it or signed up with it, never by its
email.
