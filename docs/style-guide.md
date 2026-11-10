# Style guide: colour and icons

How Delve's screens use colour and icons, so that a colour or an icon means the same thing everywhere (DEL-117).
The tokens live in `web/src/styles.css` (`:root`, and its dark-mode block); each look in `web/src/looks/` sets its own
values for the same names, and `looks/contrast.test.ts` checks them.

## Rules

1. **Colour comes from a token, never from a hex value in a component.** A component's CSS names `var(--…)`. Only the
   token blocks (`:root`, the dark-mode block, a look's `:root[data-look="…"]`) hold colours.
2. **A colour means one thing.** Pick it by what it says (below), not by how it looks next to its neighbours.
3. **Colour never says something alone.** Whatever a colour tells is also in words or an icon, for readers who can't
   tell the colours apart and for screen readers. A refused tool row says "refused"; a tool's icon sits beside its name.
4. **Text stays readable.** Body text is `--ink`, secondary text `--muted`. Semantic colours go on icons, borders and
   short marks, not on paragraphs. The exceptions are errors and notices, which have their own background pair.
5. **An icon stands for one kind of thing**, the same icon everywhere, from `lucide-react`. A decorative icon (one
   beside words that say the same) has `aria-hidden="true"`; an icon-only button has an `aria-label` and a `title`.

## The semantic colours

| Token | Means | Built on | Used for |
|---|---|---|---|
| `--tone-danger` | harm, a fight, something gone wrong | `--error` | combat and harm tools |
| `--tone-chance` | dice, luck, a check | `--warning` | rolls and checks |
| `--tone-magic` | spells and magical effects | `--dm-view` | spell tools |
| `--tone-wealth` | coin, treasure, gear | `--notice-ink` | treasure and inventory tools |
| `--tone-world` | where and when | `--accent` | travel, places, time |
| `--tone-people` | characters and what is said | `--link` | the party, NPCs, the story |
| `--tone-knowledge` | looking something up | `--muted` | reference lookups, anything else |

The older tokens keep their meanings: `--error` and `--error-bg` for a failure or a refusal, `--notice-bg` and
`--notice-ink` for a notice, `--warning` for a caution, `--dm-view` for what only the DM sees (the map's DM view),
`--accent` for the one action that matters on a screen, `--link` for links. The initiative timeline's sides use the map
markers' colours (party blue, ally green, enemy red), the same in every look.

## Tool rows

Each DM tool in the story (the host's and co-hosts' tool rows, and the "N tools" chip) shows its kind's icon, in its
kind's colour, before its name. The kinds are in `web/src/play/toolKinds.ts`:

| Kind | Icon | Colour | Tools, for example |
|---|---|---|---|
| chance | Dices | chance | `roll`, `saving_throw`, `morale_check`, `adjudicate` |
| combat | Swords | danger | `setup_combat`, `combat_round`, `resolve_attack`, `interrupt` |
| body | HeartPulse | danger | `apply_damage`, `apply_heal`, `add_condition`, `rest` |
| magic | Sparkles | magic | `cast_spell`, `memorize_spells`, `apply_effect` |
| wealth | Coins | wealth | `award_treasure`, `inventory`, `update_coin` |
| place | Map | world | `move_party`, `travel`, `scout` |
| time | Clock | world | `advance_time`, `set_time`, `new_session` |
| party | Users | people | `create_character`, `award_xp`, `leave_party` |
| story | MessageSquare | people | `say`, `tell`, `introduce_npc`, `paint_scene` |
| lookup | BookOpen | knowledge | `monster_lookup`, `rules_lookup`, `spell_lookup` |
| other | Wrench | knowledge | a tool not yet given a kind |

A batch never shows as "batch": its row lists its steps, and each step shows as its own tool. A refused call keeps its
icon; its row turns `--error` and says "refused".

**A new tool the table can see goes in one of the kinds' lists** in `toolKinds.ts`; `tests/web/test_tool_kinds.py`
fails until it does. Add a kind only for a kind of thing none of these covers, with an icon no other kind uses.

## Alerts

A **system alert** is a message from Delve itself rather than from the screen's content: this browser can't join
voice, Delve no longer knows this browser. Alerts stack at the top of every page (`components/alerts.tsx`), the same
on every screen, map editor and print pages included. A screen's own messages (a form's error, a module's warnings) stay
on the screen as a `.notice`, next to what they are about.

- A component raises an alert while its condition holds: `useSystemAlert({ id, tone, text, dismissible?, action? })`,
  or `null` to take it down. Unmounting takes it down too.
- **Tone:** `info` (something to know, `--accent` edge), `warning` (something doesn't work here, but the rest does:
  the notice colours), `error` (something is broken and needs doing: `--error`, `--error-bg`). Each has its icon
  (Info, AlertTriangle, XCircle); a warning and an error are announced (`role="alert"`), an info is `role="status"`.
- **Dismissing:** an alert is dismissible by default, with ×. This browser remembers a dismissal by the alert's
  `id`, so give an alert an id that names its cause (`voice-unsupported`), not one that changes with each page. An
  alert that must be acted on (`events-lost`, whose action is Reload) is `dismissible: false`.
- **At most one action**, a button with a verb ("Reload"). The words say what is wrong and what to do, in the
  reader's language.
- A notice that comes and goes on its own (a job finished, something saved) is a toast (`components/Toasts.tsx`),
  not an alert.
