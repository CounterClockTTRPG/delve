# Portraits and images: styles, emotes, tokens and assetgen

Date: 2026-10-19. Status: design. Built after the settings quest is delivered, on its own branch, because master is
frozen while that quest runs. This document uses the post-settings names: **Preferences** is the install's options page,
and "Settings" means game worlds.

## Intent

While testing, the owner noticed three gaps:
- they can't pick a portrait's style (realistic, painterly…);
- portraits never show emotes;
- they can't choose Replicate, or assetgen with a local generator, for pictures.

The owner asked for token management in Preferences, and for assetgen to be offered as an alternative to Replicate.

Facts found on master b8009a6:
- **portraitgen is vendored at its latest commit.** `web/vendor/portraitgen` is at e6a94a3, the same as gitea master.
  - It has seven render styles: illustrated, realistic, painterly, inkwash, engraving, anime and pixel (`RENDER_STYLES`).
  - It has data-driven emotes in an animated SVG: blink, breathe, talk with lip-sync (`say`), smile, laugh, angry,
    afraid, upset, surprised, wink, sneer and more. It honours `prefers-reduced-motion`.
  - Delve passes no style and draws no emotes (`web/src/components/Portrait.tsx`).
- **Replicate is not offered because Delve has no token.** `images/replicate.py` registers Replicate only when it finds
  `REPLICATE_API_TOKEN` or `<data dir>/replicate-token`. Neither exists on this install.
- **Delve has no assetgen backend.** assetgen runs on this machine (port 8765), with a REST API, project style prompts,
  a job queue and a record of every model call. `GET /api/models` lists its models with a `backend` (`replicate`,
  `local`, `agent`) and a `kind`.
  - Today assetgen's local models are sound-effect models only (`sao-small`, `sao-1.0`). Its image models are all
    Replicate FLUX models.
  - The owner wants local models offered. So Delve must not hard-code assetgen's models: it reads them, and a local image
    model added to assetgen later appears in Delve without any change to Delve.

## Owner decisions (2026-10-19)

1. **The portrait style is chosen per campaign**, not per portrait and not per install. All seven portraitgen styles are
   offered.
2. **Emotes show in three places:**
   - **Speaking NPCs in the story.** An NPC's portrait next to their line shows the mood of that line.
   - **A talking animation.** The portrait talks with lip-sync while a line is read or appears.
   - **The character sheet.** A PC's portrait reflects their state: hurt, unconscious, frightened.
3. **assetgen is a picture backend, and the choice is made in Preferences.** Preferences already picks a backend and a
   model for each job (`image.portrait`, `image.scene`, `image.possession`). assetgen joins that list as a backend. Its
   models are whatever assetgen reports for kind `image`, Replicate-backed or local, each labelled with its backend and
   price.
4. **Tokens in Preferences.** These can be entered, replaced and removed:
   - the **Replicate token**;
   - **the assetgen URL** and its token, if assetgen asks for one.

## Goals

- **Campaign portrait style.** The campaign gets a stored portrait style (a migration) with a choice on the campaign's
  page. The default is `illustrated`, as today. The style list is portraitgen's `RENDER_STYLES`. Every portraitgen
  portrait in that campaign renders in the style: sheets, the party, NPCs, the story and the join page.
  Painted pictures (Replicate, assetgen) keep their style from the campaign's tone, as today. assetgen also applies its
  project style prompt.
- **Emotes.**
  - **The story.** The DM's narration can carry a mood for a speaking NPC's line. This goes through the existing story
    entry or tool fields: the builder picks the smallest addition, and `dm.md` says when to use it. The NPC's portrait
    beside that line plays the matching emote once, then rests.
  - **Talking.** While a line streams in, or the read-aloud plays if there is one, the speaker's portrait plays `talk`
    with the line as `say`.
  - **The character sheet.** The state maps to an emote: below a third of HP is hurt (`upset` or `afraid`), 0 HP or
    unconscious is `sleep`, and a frightened condition is `afraid`. Otherwise idle (`blink`, `breathe`).
  - In every case, `prefers-reduced-motion` gives the still portrait, which portraitgen already does. No emote runs on
    lists of many portraits, beyond idle.
- **Preferences: tokens.** There is a "Connections" section. The UI never shows a stored token; it only says "set" with
  a way to replace or remove it.
  - **Replicate:** saving the token writes `<data dir>/replicate-token` (mode 0600). Without a restart, Replicate is
    registered or unregistered and appears in or disappears from the job choices. `REPLICATE_API_TOKEN` in the
    environment still wins and is shown as "from the environment".
  - **assetgen:** the URL (default `http://localhost:8765`) and an optional token are stored as a secret.
  - A "Test" button checks each connection: Replicate's account endpoint, and assetgen's `GET /api/models`.
- **The assetgen backend** is `images/assetgen.py`, next to `replicate.py`, over `httpx`.
  - It keeps one assetgen project for the install (named `delve`) and creates it if it is missing.
  - It submits an image job for portraits, scenes and possessions, waits on assetgen's queue, and downloads the PNG.
  - It sends the brief the Replicate backend builds (`full_prompt` with tone), unless assetgen applies the project style.
    The builder settles the interplay so the style isn't doubled.
  - Its capabilities list assetgen's `image` models, each labelled with its backend (`replicate` or `local`) and price.
  - When assetgen is unreachable, the job fails with a clear message, as Replicate does. It never falls back to another
    paid backend silently.
- **Docs.** The glossary gets portrait style, emote and Connections. The data dictionary gets the campaign column and
  the secrets. The backlog gets "a local image model in assetgen": the owner's wish, and assetgen's own project.

## Non-goals

- Adding a local image model to assetgen. That is assetgen's own project, and Delve picks it up when it exists.
- Choosing a style per portrait or per install.
- Custom emotes. Delve uses portraitgen's built-ins.
- Read-aloud audio, if Delve doesn't have it yet. The talk animation then follows the streaming text.
- Updating the vendored portraitgen beyond the play-once change (see "Calls made for the owner").

## Anti-goals

- A token reaching a browser, a log, an error message, an export or the DM.
- A portrait that animates constantly and distracts in play. Emotes play once for a line or a change, and only blink and
  breathe stay on.
- Hard-coding assetgen's model list, which would hide a local model the owner adds later.
- Breaking existing portraits: stored traits and seeds render as before, in the default style.

## Constraints

- Tests never call Replicate or assetgen. Use fake HTTP (`httpx.MockTransport`), as `replicate.py`'s tests do.
- `make ci` green. The browser e2e checks the style choice and one emote in the story with the fake DM.
- Secrets live under the data dir or in the secret store Delve already has (the builder checks for one). They are never
  in the `settings` (now Preferences) JSON.

## Owner decision after the builder check

5. **NPCs speak through a say tool.** Today the story draws no portraits and has no speaker, and one `dm_text` holds a
   whole reply that can quote several NPCs. So:
   - The DM gives each NPC line as its own story entry, with speaker, mood and text, through a new DM tool
     (say-style). Narration stays its own entry.
   - The story shows the speaker's portrait beside that entry. The portrait plays `talk` with the line as `say` while it
     streams in, then plays the mood's emote once.
   - Translation and `player_view` treat a said line like narration.
   - `dm.md` tells the DM to use the tool for every quoted NPC line.

## Calls made for the owner (to confirm or overrule)

- **Tokens and the assetgen URL are owner-only.** The rest of Preferences stays organiser-only. A Replicate token spends
  the owner's money, and assetgen has no authentication of its own. The assetgen URL must be http or https, on loopback
  or a private LAN address, to rule out server-side request forgery. The optional assetgen token field is kept, as the
  owner asked, even though assetgen doesn't ask for one today.
- **The paid-images gate goes per model.** The campaign's `paid_images` switch gates Replicate, and assetgen models whose
  backend is `replicate`. assetgen's `local` models are free and are not gated. The hint names the reason.
- **Emotes play once through an upstream portraitgen change.** portraitgen writes every emote as an infinite CSS
  animation. Add a play-once option (an iteration count, plus the emote's duration exported) to portraitgen itself, the
  owner's repo on gitea, with its own tests. Then copy the new commit into `web/vendor/portraitgen`. This replaces the
  non-goal "updating the vendored portraitgen". 0 HP uses the built-in `sleep` (there is no `snore`), looping, since it
  is a held state.
- **assetgen is registered once its URL is saved** (there is no default registration). Its models are read live from
  `GET /api/models`, cached for about a minute, so a model added to assetgen later appears without a restart. This makes
  the backends registry able to add, update and remove a provider at run time. When a saved choice points at a model
  that is gone, or at assetgen while it is down, Preferences shows a "can't be used" warning, and the job fails with a
  clear message. Saving such a choice isn't refused, because assetgen may be down only for a moment.

## Left to the builder

- The exact mood vocabulary the DM may use, a subset of portraitgen's emotes.
- How a mood is carried on a story entry.
- The thresholds for hurt.
- How to wait on assetgen's job queue: polling or its events.
- The layout of the Connections section.
