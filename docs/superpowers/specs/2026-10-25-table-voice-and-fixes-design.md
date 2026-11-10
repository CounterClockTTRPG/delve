# Voice at the table, the initiative strip, and module fix-ups

Date: 2026-10-25. Status: design. A Guild quest on master (d02ecfb and later).

## Intent

The owner's sessions (Phlan, Barrowmaze) and module imports showed a handful of things that get in the way at the
table and after an import. This project fixes them in one quest:

- **A. Voice between players.** Players may sit in their own homes and join over the internet (through the owner's
  Cloudflare tunnel). Some sessions are chat-only, some voice. A player who wants to talk can; nobody has to.
- **B. The initiative strip, with ongoing actions.** The table can't see the order of a fight, and a spell being cast,
  a scroll being read or a potion being drunk is invisible until it lands or breaks.
- **C. A character leaves the party** (backlog Features 26).
- **D. Retry a failed beat** (backlog Features 33).
- **E. The combat fixes** of backlog Fixes 10.
- **F. Module fix-ups after an import:** comments on the PDF form (backlog Features 17), comments on a finished module
  that Claude acts on, and closing the conversion's questions and doubts box. These replace backlog Features 27
  (Optimize), which the owner considers mostly done by the thorough conversion.

## Owner decisions (2026-10-25)

1. Scope: backlog 33, 27 (reduced as F), 17, Interface 9, 26, the combat fixes in Fixes 10, plus voice.
2. **Voice is relayed through Delve**, over the same port as the website, so it works through the tunnel. Not
   peer-to-peer; no TURN server, no third-party relay.
3. **Voice is optional, per player**: nobody is in voice until they join. Not everybody has a microphone.
4. **A campaign-level voice setting**, so a host who doesn't want voice can switch it off.
5. **Initiative is configurable per campaign**, defaulting to per-combatant initiative.
6. **Ongoing actions** (spells, scrolls, potions and other long actions) show as ongoing and can be interrupted.
7. **Optimize is mostly done.** What remains: comments on a module ("exit X is not yet in place, fix it") instead of
   editing a text or map by hand, and being able to hide or close the conversion's review box on a module's page.
8. **The initiative timeline shows a round's outcomes once the DM's narration of it has arrived**; no per-action
   engine split.
9. **iPhone (Safari) players may be listen-only for now**; no bundled encoder.

## Constraints

- Everything a seat sees still passes the fourth wall (`delve.play.audience`): no DM secret reaches a seat through any
  new route, event or WebSocket message. Unseen monsters stay unnamed on the initiative strip, as on the map.
- Every new UI string is in `en.json` and `nl.json`. Desktop and phone (390 px) both work.
- New status words and terms go in the glossary.
- `make ci` stays green; new behaviour is test-first, as in the earlier plans.
- The uncommitted work on `fix/sort-pictures` (thorough conversion `pipeline.py`, `workspace.py`, `sort.md` and their
  tests) is settled (committed and merged, or shelved) before the quest starts, since a quest freezes master.

## A. Voice between players

**What a player sees.**
- When voice is allowed in the campaign, the play screen has a **Join voice** button (desktop: in the play header or
  beside the seat indicators; phone: on the Table screen). Delve asks for the microphone only when it is pressed.
- Joining means **listening**. If the player has no microphone, or refuses it, they still hear the others and say so
  in the UI ("listening only"). A player with a microphone can **mute and unmute** themselves; the mic is open while
  unmuted (no push-to-talk; *my call*, push-to-talk could be a later preference).
- **Leave voice** ends it. Reloading or leaving the play screen leaves voice.
- The seat indicators show who is in voice, who is muted or listening only, and light up who is **speaking** (*my
  call*).
- The browser's echo cancellation, noise suppression and automatic gain stay on (`getUserMedia` constraints).

**Who.** Hosts, co-hosts and players can talk. Observers can listen but not talk (*my call*). Only seats of that
campaign; a seat that left can't join.

**The campaign setting.** **Voice: allowed / off** on the campaign page, set by the host. Default **allowed** for new
and existing campaigns (*my call*: nobody is in voice until they join, so allowed costs nothing). Switching it off
disconnects everyone in voice at once and hides the button. Stored with the campaign (a migration).

**The relay.**
- A WebSocket route on Delve's own port, per campaign (for example `/api/campaigns/{id}/voice`), under the same
  identity as every other route (account session, seat token or owner token) and the guard's Host/Origin checks.
  uvicorn[standard] already carries WebSocket support. It must work through a Cloudflare tunnel and on the LAN.
- Each browser encodes its microphone (Opus is the obvious choice; WebCodecs `AudioEncoder` or an equivalent that
  streams small independently decodable frames) and sends frames; Delve forwards each frame to the campaign's other
  listeners, tagged with the sender's seat. Delve doesn't decode, mix or store audio.
- Each browser plays each speaker through a small jitter buffer (an `AudioWorklet` or equivalent) and mixes them
  locally.
- Sized for about five people. A cap per campaign (for example 8 in voice) and a cap per sender's frame rate and size,
  so one client can't flood the others.
- Target delay: under ~400 ms mouth-to-ear over the tunnel. Speech bitrate around 24–32 kbit/s.
- **Nothing is recorded or transcribed.** Voice never reaches the DM, the story, Ask, a novel or the logs (frame
  counts and joins/leaves may be logged, never audio).
- Browsers: current Chromium, Firefox and Safari, desktop and phone, for listening. Talking needs the browser's own
  encoder; **where it has none (likely Safari and every iPhone browser), the player is listen-only and the UI says so
  (owner, 2026-10-25)**. No bundled WebAssembly encoder for now. Where a browser can't even play, the button says why.

**Left to the builder:** the exact framing and codec path, the jitter buffer's size, how speaking is detected (level
on the sender, sent as a flag, or on the listener), reconnect behaviour after a dropped socket, and where the button
sits exactly.

## B. The initiative strip and ongoing actions

**What exists.** `delve.rules.adnd2e.combat` already rolls initiative per combatant every round (d10 plus weapon speed,
or plus the declared spell's casting time from the reference's `casting_time_init`), acts in that order, and disrupts
a spell when its caster takes damage before it goes off ("spell disrupted!"). The order lives only in the DM's tool
results (`combat_round`, `setup_combat`'s `order`).

**Initiative mode, per campaign.** A campaign setting **Initiative: per combatant (default) / per side**, set by the
host (stored with the campaign; the same migration as voice is fine). Per side is the PHB's standard method (ch. 9):
one d10 per side, the lower acts first, ties simultaneous. How casting times and weapon speeds count in per-side mode
follows the PHB ch. 9 rules; the builder cites what it implements. Switching mode takes effect at the next round.

**Ongoing actions.**
- A combatant can be busy with a **long action**: casting a spell, reading a scroll (the spell's casting time), drinking
  a potion, using another magic item (PHB ch. 9's standard initiative modifiers for items: potion, ring, rod, stave,
  wand…), or another declared action that takes time. The engine stores it on the combatant: what, when it started,
  when it completes (segment of a round, or a later round).
- **Actions longer than a round carry over** to the following rounds until they complete or break. Today `casting` is
  cleared at the end of each round (`_finish_casting`); that changes for multi-round actions.
- **Interruption:** damage, or a failed save or other disruption the rules name, before completion breaks a spell or
  scroll (as today, extended across rounds). What interrupts a potion or another action follows the rules where they
  say; otherwise the DM decides with a tool (`interrupt` or an `adjudicate` outcome). The result names why ("Mirela
  was hit; *Sleep* is lost").
- The DM's tools see the ongoing state (in `combat_status` and the round results), so the DM can rule on it.

**The strip is a timeline** (the owner's wording in backlog Interface 9, 0842afb, 2026-10-25).
- While a fight is on, a strip above the story shows the round number and the round's initiative counts along an axis
  (1 to 10 and beyond). Each combatant stands at the count they act on (portrait or token, name, side by colour), so
  two who act on the same count stand together and a slow weapon or a long spell lands later in the round.
- A marker shows who acts now and who has acted; who is down or fled is marked.
- Per-side mode places each side's group at its side's count; per-combatant mode places each combatant at their own.
- An ongoing action is drawn as a span from its start to the count it completes on ("casting *Sleep*", ending at 7), so
  it can be seen and spoiled; one that runs past the round runs off the end ("next round"). Completed and interrupted
  actions are marked as such for the rest of the round.
- Unseen monsters stay unnamed, as on the map. Nothing DM-only (HP of monsters, their declared actions) shows to seats;
  a monster's ongoing spell shows only once the party could notice it (*my call*; the builder decides what counts as
  noticed, from the fourth-wall rules).
- On a phone: a thin row at the top of the story, scrolling sideways.
- **When outcomes show (owner, 2026-10-25):** the order and the ongoing actions show as soon as the round's
  initiative is rolled. A round's outcomes (who acted, hits that downed someone, an interrupted spell) show once the
  DM's text for that round has arrived, never ahead of the narration. `combat_round` keeps resolving a round in one
  call; no engine split into per-action calls.
- Fed by a read route and SSE events (initiative rolled, the round's outcomes released, the fight ended).

## C. A character leaves the party (backlog Features 26)

As the backlog describes it:
- A PC leaves the party without being deleted, with a reason: **died, retired or left**. It drops out of the party
  sidebar and "Acting for", keeps its sheet, history and place in the story, and is listed folded ("Fallen: Tansy";
  the label fits the reason).
- The DM does it with a tool (the character and why); an organiser with a button on the campaign page.
- It can be undone (a raise dead, a return), by the DM's tool or the button.
- A character who leaves during a fight leaves the fight (*my call*).
- Builds on `delve.dm.tools.party`, `life_conditions`' `dead`, `web/src/play/PartySidebar.tsx`, the composer's
  `act-for`, and the campaign page's character list (where Delete stays for real mistakes).

## D. Retry a failed beat (backlog Features 33)

- A beat that ended in a **retryable** error (`DMError.retryable`: the usage limit, a crash, a restart mid-beat) shows
  **Retry** on its entry in the story.
- Retry plays the beat again with the same acts; nobody retypes or writes "(continue)".
- Who can press it: the host and the seats whose acts were in that beat (*my call*).
- Only the **latest** beat can be retried, and only while no newer beat has opened. Once someone acts again, the
  failed beat's Retry goes away (*my call*: replaying a stale beat into a story that moved on is worse than retyping).
- What the DM already applied before the failure (Phlan beat 119's two combat rounds) is not undone; the retried beat
  tells the DM what was already applied (from the beat's tool log) so it carries on rather than repeats.
- A usage-limit pause says when the limit ends (from the CLI's rate-limit event already kept in `account.json`), and
  Retry is available then.
- A restart during a beat leaves it retryable (today it is just cut off).

## E. Combat fixes (backlog Fixes 10)

- Sleep (and any spell) can be declared in round 1 of `combat_round` after `setup_combat`; the declaration hint stops
  contradicting itself (`rules/adnd2e/combat.py` `declare`).
- "Natural 20" in a round's notes says it is an automatic hit, not a critical hit.
- A weapon given as "Dagger" in melee resolves to the melee dagger, not "Dagger (thrown)".
- `setup_combat "rat, giant"` matches the giant rat, not the first 3+1 HD creature; the matching prefers exact and
  closer names.
- A module's stated stats (AC 5 zombies) win over the reference's. `setup_combat` already takes per-group overrides
  (`ac`, `hp`, `thac0`…); the fix is that the DM is told to pass them: `setup_combat`'s hint and result say when the
  module's keyed encounter states different stats than the reference row, and dm.md asks for the module's numbers
  (*my call*: no new link between fights and module content).
- `adjudicate` works outside a fight; `say` works for a PC the player handed to the DM; `add_combatant` takes `hp_max`.

## F. Module fix-ups

**F1. Comments on the PDF form (backlog Features 17).** A text area on the PDF form ("the maps are already in dungml:
don't draw them", "the room key starts on page 40", "keep the book's spelling"), sent with `POST
/api/conversions/pdf`, kept on the job, and given to the conversion's prompts, quick and thorough. The generate box
points to the PDF form when what's typed looks like an import (a file name, "import", "convert") (*my call*, from the
backlog).

**F2. Fix-it comments on a module.**
- On a module's page, an organiser writes a comment in plain words: "exit X is not yet in place, fix it". Optionally
  tied to a map, a room/key, a text or an entity (*my call*).
- Sending a comment starts its job at once. A module runs one fix-it job at a time: comments sent while one is
  running or waiting for review queue up and run together as the next job, once the previous one is kept or rejected
  (*my call*: so no two jobs build on the same revision and refuse each other's Keep).
- Each job runs as a background job (like a conversion: the runner, progress, the Modules list's running row) in
  which Claude changes only what the comment asks, with the module's own editing operations (texts, entities, keys,
  maps in the map language).
- When it finishes, the organiser sees what it would change (a text diff, the map before and after, the entities
  added, changed or removed) and **keeps** or **rejects** it. Nothing is saved before Keep. A kept change is a new
  module revision, as the editor's saves are, so campaigns stay pinned.
- A comment's status: open, working, ready to review, kept, rejected, failed (with its reason and a retry). A comment
  can also be closed without running it. These words go in the glossary next to the module and campaign statuses.
- If the module changed since the job started, Keep refuses and offers to run the comment again on the new revision
  (*my call*).
- The existing remarks under a conversion's questions (written into "Notes from making this module" for the DM) stay
  as they are; fix-it comments are a separate thing.

**F3. Closing the questions and doubts box.** The box on a module's page with a conversion's questions and doubts
(`web/src/module/MakingQuestions.tsx`: "sketched-map", "missing-room", "picture-unsure"…) stays forever today.
- Each question and doubt can be **closed** once dealt with, and reopened.
- When everything in it is closed, the box folds to one line ("All 12 dealt with · Show"). A **Close all** hides it in
  one click.
- Closed state is stored server-side with the job's questions, so every organiser sees the same.
- Closing only hides; it doesn't change "Notes from making this module" or what the DM is told.

## Non-goals

- Peer-to-peer audio, a TURN server or a paid relay; video; recording or transcribing voice; voice reaching the DM.
- Push-to-talk (a later preference, if wanted).
- The full Optimize job of backlog 27 (stat-line checks, NPC stats from prose, audiences in bulk): struck as mostly done.
- The party's journal (backlog 28), retry for non-retryable errors, Cloudflare setup (the owner does it).

## Anti-goals

- Delve asks for a microphone without the player pressing Join voice, or voice turns on by itself.
- Any audio stored on disk or sent anywhere but the other people in voice.
- The strip or a voice message leaking what the party can't know (unseen monsters, monster HP, a secret act).
- A fix-it comment that saves changes the organiser didn't see and keep, or that changes parts of the module the
  comment didn't ask about.
- Retry that applies a beat's effects twice.

## Backlog bookkeeping

Strike Features 17, 26, 27 (with a note: reduced to F2 and F3), 33, Interface 9 and the combat lines of Fixes 10 (Sleep
in round 1, natural 20, Dagger, rat giant, zombie AC, adjudicate/say/add_combatant) when they are done. Voice is new
and needs no backlog entry.

## Left to the builder

The order of the work and how it splits into tasks; table and column names; route shapes; the exact rules text cited
for per-side initiative and item use times; the codec and buffering details of voice; the layout details on desktop
and phone within what's said above.
