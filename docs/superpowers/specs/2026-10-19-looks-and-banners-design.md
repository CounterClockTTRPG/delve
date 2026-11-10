# Looks and campaign banners

Status: design, from a conversation with the owner on 2026-10-19. Not yet planned. Build it after the settings quest
(20261019-54c4380e, which makes Preferences) and the portraits-and-images work
(`2026-10-19-portraits-and-images-design.md`, which adds the image connections) are delivered.

## Intent

Delve's look is fantasy, but quiet: a light, cool green-grey (dark when the device is dark), Palatino-style text, no
textures and no pictures on empty screens. The owner wants stronger looks to choose from. The inspiration is ttrpg2,
which had a warm "gold and wood" feel and a painted picture on an empty campaign. It is inspiration only: nothing is
copied from ttrpg2, neither colours nor images.

A campaign also gets a painted banner, like ttrpg2's campaign banners. It is the picture on the campaign's empty
screen, and the module's page shows its campaigns' banners as thumbnails.

## Owner decisions (2026-10-19)

1. **A few built-in looks to pick from.** No theme editor and no custom looks.
2. **Each person picks for their own screen.** A look is a personal choice. It is not a campaign or install setting,
   and it never changes what anyone else sees.
3. **Three looks:**
   - **Delve today**, the current look, unchanged.
   - **Gold and wood:** warm and dark, with gold, carved capitals, candlelight and a **dark oak** sidebar texture
     (ambientCG `Wood051`, chosen from four).
   - **Dark dungeon:** cold stone and near-black, lit only by torch orange, with old-print lettering and a **rough
     cave rock** background (ambientCG `Rock030`, chosen from four).
4. **Textures are real photo textures that tile**, not CSS stripes. The owner rejected the CSS wood-grain sketch.
5. **Pictures are painted, like the other painted pictures.** They are not shipped with Delve.
6. **One banner per campaign**, painted **automatically when the campaign is made**.
7. **The module's page shows the banners of its campaigns as clickable thumbnails.** A click opens that campaign. The
   module has no picture of its own in this design.

The mockups the owner chose from are in `.superpowers/brainstorm/3793808-1792434368/content/` (`three-looks.html`,
`gold-wood-textures.html` (B), `dungeon-stone-textures.html` (D)). That folder isn't committed. The textures came from
ambientCG under CC0.

## Goals

### Looks

- **A look picker reachable by everyone who uses Delve:** the owner and organisers in Preferences, and seats (players
  who came in by a join link, who have no Preferences) from the play screen.
- **The choice stays in that browser** (local storage) and applies before the first paint, so a page never flashes in
  the wrong look. A browser with no choice (or no storage) gets Delve today.
- **Delve today stays exactly as it is,** light and dark following the device.
- **Gold and wood** (from the mockup):
  - near-black warm brown page (about `#17110b`) with a faint warm glow in the top-left corner;
  - parchment text (about `#ecdcb8`), and pale gold headings (about `#f0d79e`);
  - gold accents and buttons, drawn as a gradient (`#f0d196` → `#b8904f`) with dark text on them;
  - cards a shade warmer than the page, with a thin brown border and a faint gold highlight on the top edge;
  - headings, the menu and buttons in Cinzel (spaced capitals); body text in EB Garamond;
  - the sidebar in dark oak (`Wood051`), lightly darkened, with a gold right edge and an inner shadow; the current
    item is a gold plate with dark text.
- **Dark dungeon** (from the mockup):
  - the page is rough cave rock (`Rock030`) under a heavy dark wash, with a faint torch glow from the top right;
  - pale grey text (about `#c9ccc8`) and near-white headings with a faint orange glow;
  - torch orange (about `#e08a3c`) as the only bright colour: buttons, the current menu item and links;
  - the sidebar near-black; cards near-black and slightly see-through, with a grey left rule;
  - headings and the menu in IM Fell English SC; body text in IM Fell English.
- **The look reaches every screen:** play, campaigns, modules, maps, the editor, Preferences, the join page, dialogs
  and notices. It colours what's on the screen; it never changes layout or behaviour.
- **Every look stays readable:** text and controls meet WCAG AA contrast against their real background (the texture
  included), and focus rings show.

### Banners

- **A campaign gets a banner when it is made:** a wide painting of its module's world, with no characters up front,
  in the style painted pictures already take from the campaign's tone. It is painted in the background, so making the
  campaign never waits for it; while paid images are off, it waits for them (decision 8).
- **Where it shows:**
  - the play screen while the story is empty, above "The story starts with your first act", for every seat;
  - the campaign's page;
  - the module's page, as a row of thumbnails of its campaigns' banners, each opening its campaign.
- **The owner (and organisers) can paint it again,** with an optional hint ("the barrow mounds in mist"), from the
  campaign's page. The new banner replaces the old one.
- **No banner is not an error.** With no image model set up, a gate closed or a failed painting, the screens show as
  they do today. A failure is reported where the owner will see it (the campaign's page), not to players.
- **Existing campaigns get no banner by themselves.** They can paint one from the campaign's page.
- **The brief never leaks the module's secrets.** It is built from what any player may know: the module's title, its
  summary or description (the metadata fields), the setting's name and the campaign's tone. Never keyed text, DM
  notes or entities.

## Non-goals

- A theme editor, custom colours or uploaded textures.
- A look per campaign, per seat on the server, or per install.
- Light versions of the two new looks (they are dark only).
- Changing map styles: maps keep their own renderers, and printed maps and print views don't follow the look.
- A picture for the module itself (the `.dscn` cover stays as it is).
- Pictures for other empty screens (an empty module list, an empty map).

## Anti-goals

- **A look that hurts reading or play:** text on a busy texture, low contrast, or textures that slow the play screen.
- **Anything that looks copied from ttrpg2:** its colours, its pictures or its exact typography.
- **A banner that spoils the module** for players.
- **Making a campaign slower or more fragile:** creation must never fail, or wait, because of the banner.
- **Calls to outside services when the page loads:** fonts and textures come from Delve itself, not Google Fonts or a
  CDN. Delve runs on a home network.

## Constraints

- **Colours are tokens.** `web/src/styles.css` already defines the look as CSS custom properties on `:root` (`--bg`,
  `--surface`, `--ink`, `--accent`, …), with a dark set under `prefers-color-scheme`. A look is another set of those
  tokens, plus a few new ones (textures, display font) that Delve today leaves empty. Colours hard-coded in components
  (about 14 in `web/src/**/*.tsx`) move to tokens.
- **The editor follows too.** Monaco and the `.dmap` language (`web/src/editor/`) pick a light or dark editor theme;
  both new looks use the dark one.
- **Fonts are shipped with Delve:** Cinzel, EB Garamond, IM Fell English and IM Fell English SC are under the SIL Open
  Font License. Self-host them (for example the `@fontsource` packages), and load a look's fonts only when it's
  chosen.
- **Textures are shipped with Delve,** resized and compressed (for example 512 px JPEG, well under 100 KB each), with a
  note of their source and CC0 licence (ambientCG `Wood051`, `Rock030`) next to them.
- **Banners are painted pictures.** They go through `delve.play.images` like scenes: a `campaign_images` row with a new
  kind `banner`, painted by `schedule`/`paint` in the background, picked up again by `resume` after a restart. The
  image backend, the model choice and the tone clause (`delve.images.replicate.full_prompt`) are reused.
- **Banners are wide.** Scenes are `16:9` (`ASPECT_RATIOS`); a banner wants a wider ratio, so it needs its own job (or
  its own entry in `ASPECT_RATIOS`).
- **Paid pictures are gated.** `paid_images` is a play setting, off for every campaign until the host turns it on
  (`delve.play.images.paid_images`); with the portraits-and-images work the gate goes per model. A new campaign
  therefore starts with it off: decision 8 says how the banner waits for it.
- **Docs:** the glossary gets look and banner; the data dictionary gets the new image kind and the look's storage key;
  the README's Play and Modules sections mention them.
- **Tests:** `make ci` green; a web test per look switch (tokens applied, choice remembered, no flash); a browser e2e
  that switches looks, and one where a campaign made with the fake image backend, once its host turns paid images on,
  shows its banner on the empty play screen and on the module page.

## Calls made for the owner (to confirm or overrule)

1. **Delve today is the default** for a browser that hasn't chosen.
2. **The banner shows in every look,** Delve today included; the look only frames it (a gold edge, a dark rule).
3. **The banner is painted in the campaign's tone style,** like scenes. (The conversation first said "the portrait
   style": that's the free portraitgen style, which painted pictures don't use.)
4. **The look picker:** in Preferences for organisers, and a small "Look" control on the play screen for seats. Its
   options show each look's name and a small swatch.
5. **The choice is per browser,** not per person: Delve has no personal accounts, and a seat is a campaign's, not a
   person's.
6. **Painting again replaces** the banner; the old one isn't kept.
7. **The campaign's page shows the banner** too, because that's where "paint again" lives.

## Owner decision after the builder check (2026-10-19)

8. **The banner waits for the gate.** A new campaign starts with paid images off (`DEFAULT_PLAY_SETTINGS` in
   `delve.play.table`), and no free model paints pictures yet, so the banner can't be painted at creation. Instead:
   - making a campaign asks for its banner; while the gate is closed for the chosen model, the request **waits** (a
     waiting state on the banner row, or on the campaign) instead of being refused;
   - when the host turns paid images on (the play-settings route), or a free model becomes the choice, a waiting
     banner is **painted then, automatically**, once;
   - **"Paint again" obeys the gate too:** with it closed, the campaign's page says why (the `PAID_HINT` wording) and
     offers no button that would spend.
   - With the gate already open at creation (a free model), the banner is painted at once.

   This also settles the tone: the banner takes the campaign's tone **when it is painted**, which by the time the
   host opens the gate is usually the real one. A later tone change doesn't repaint it; "paint again" does. The e2e
   check turns paid images on for its campaign (with the fake backend) and then sees the banner appear.

## Left to the builder

- The token names, and how a look is applied (an attribute on `<html>` and token sets per attribute is the expected
  way).
- The exact colours, within the descriptions above, tuned to pass contrast on the real textures.
- How dark the texture washes are, and how the textures tile on a large screen.
- The banner's aspect ratio, the brief's wording ("wide cinematic landscape, no characters in the foreground"), and
  whether the new job gets its own row in Preferences or follows the scene's choice.
- The banner's size and crop on each screen, and the thumbnail size on the module page.
