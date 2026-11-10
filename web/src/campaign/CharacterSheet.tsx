import type { Character, SheetEmote, XpProgress } from "../api";
import Portrait from "../components/Portrait";
import { useLanguage, useT, type Translate } from "../i18n";
import { term } from "../i18n/terms";
import { queuedLine } from "../components/waiting";
import { EditPortraitLink } from "./PortraitEditor";
import { RepaintLink } from "./RepaintPortrait";
import { renderMarkdown } from "../play/markdown";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"] as const;

/** A skill by its name: the thief skills translated, any other as the sheet has it, with spaces for underscores. */
function skillName(t: Translate, skill: string): string {
  const key = `skill.${skill}`;
  const name = t(key);
  return name === key ? skill.replace(/_/g, " ") : name;
}

/** A saving throw by its key: the rulesets' saves translated, any other as the sheet has it, with spaces. */
function saveName(t: Translate, save: string): string {
  const key = `save.${save}`;
  const name = t(key);
  return name === key ? save.replace(/_/g, " ") : name;
}

function signed(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** The parts an attack's worked-out THAC0 adds up from, as one line: "THAC0 18, Strength -2, Magic -1". */
function thac0Parts(t: Translate, parts: [string, number][]): string {
  const shown = (part: string, value: number) => (part === "base" || part === "stored" ? String(value) : signed(value));
  return parts.map(([part, value]) => t(`sheet.thac0Part.${part}`, { value: shown(part, value) })).join(", ");
}

/** Whether the reader asked for less motion: then a portrait is still. */
function reducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * What the portrait plays of the character's state (`emote`, the server's `sheet_emote`): `sleep` loops, as a held
 * state; `afraid` and `upset` play once, again each time the state changes to them, and rest on blinking and
 * breathing; any other state blinks and breathes. Nothing moves under reduced motion.
 */
function stateLook(emote: SheetEmote): { emotes?: string[]; once?: boolean } {
  if (reducedMotion()) return {};
  if (emote === "sleep") return { emotes: ["sleep", "breathe"] };
  if (emote === "afraid" || emote === "upset") return { emotes: [emote, "blink", "breathe"], once: true };
  return { emotes: ["blink", "breathe"] };
}

/**
 * A read-only character sheet: the abilities, HP, AC, THAC0, saves, attacks (each with its THAC0), proficiencies,
 * thief skills, natural abilities, inventory with its encumbrance band, the spell loadout with what is memorized and
 * what has been cast, and the background, under its portrait, which shows the character's state. Everything shown comes from the server as it is. An NPC's story and
 * disposition show only with `organiser`, and only the organiser's route sends them. With `mayRepaint`, a small
 * Repaint portrait (or Try again, for one that failed) under the head (DEL-135).
 */
// The classes that cast from a spellbook: the mage or magic-user, its specialists (the illusionist among them), and
// the bard.
const SPELLBOOK_CLASSES = new Set([
  "mage", "magic-user", "wizard", "illusionist", "abjurer", "conjurer", "diviner", "enchanter", "invoker",
  "necromancer", "transmuter", "bard",
]);

function keepsSpellbook(levels: Record<string, number>): boolean {
  return Object.keys(levels).some((cls) => SPELLBOOK_CLASSES.has(cls.toLowerCase()));
}

export default function CharacterSheet({
  character,
  organiser = false,
  mayRepaint = false,
}: {
  character: Character;
  organiser?: boolean;
  /** Whether the reader may repaint the portrait (DEL-135), or edit it while portraitgen draws PCs (DEL-238): the
   * host, an organiser, or the character's player. */
  mayRepaint?: boolean;
}) {
  const t = useT();
  const { sheet, state, encumbrance } = character;
  const emote = character.emote ?? "idle";
  const headingId = `sheet-${character.id}`;
  const classes = sheet.cls
    .split("/")
    .map((c) => c.trim())
    .filter(Boolean)
    .map((c) => {
      const level = sheet.levels[c.toLowerCase()];
      const name = term(t, "class", c);
      return level === undefined ? name : `${name} ${level}`;
    })
    .join(" / ");
  const who = [term(t, "race", sheet.race), term(t, "gender", sheet.gender), term(t, "alignment", sheet.alignment)]
    .filter(Boolean)
    .join(", ");
  const scores = sheet.ability_scores ?? {};
  const abilities = ABILITIES.filter((a) => scores[a] !== undefined);
  const skills = Object.entries(sheet.skills ?? {});
  const weaponProfs = sheet.weapon_profs ?? [];
  const nwps = sheet.nwps ?? [];
  const naturalAbilities = sheet.natural_abilities ?? [];
  const story = organiser && character.kind === "npc" ? (sheet.notes_md ?? "") : "";
  const disposition = organiser && character.kind === "npc" ? sheet.disposition : undefined;
  const inventory = state.inventory ?? [];
  const memorized = state.memorized ?? [];
  // Known spells are a spellbook's: a priest may pray for any spell of their spheres, so a list means nothing there.
  const known = keepsSpellbook(sheet.levels) ? (sheet.spell_loadout?.known ?? {}) : null;
  const loadout = sheet.spell_loadout?.default ?? {};
  const spellLevels = [
    ...new Set([...Object.keys(sheet.spell_slots), ...Object.keys(known ?? {}), ...Object.keys(loadout)]),
  ].sort((a, b) => Number(a) - Number(b));
  const hasSpells = memorized.length > 0 || spellLevels.length > 0;

  return (
    <article className="sheet" aria-labelledby={headingId}>
      <header className="sheet-head">
        <Portrait
          campaignId={character.campaign_id}
          portrait={sheet.portrait ?? null}
          name={emote === "idle" ? character.name : t(`sheet.portraitState.${emote}`, { name: character.name })}
          size={72}
          npc={character.kind === "npc"}
          {...stateLook(emote)}
        />
        <h3 id={headingId}>{character.name}</h3>
        <span className="tag">{t(character.kind === "npc" ? "sheet.npc" : "sheet.pc")}</span>
        {character.portrait_painting && (
          <p className="sheet-who" role="status">
            {queuedLine(t, character.portrait_painting) ?? t("sheet.portraitPainting")}
          </p>
        )}
        {mayRepaint &&
          (character.portrait_editable ? <EditPortraitLink character={character} /> : <RepaintLink character={character} />)}
        {(classes || who) && (
          <p className="sheet-who">
            {classes && <span className="sheet-class">{classes}</span>}
            {who && <span>{who}</span>}
          </p>
        )}
        {(sheet.size || Boolean(sheet.ac_vs_larger)) && (
          <p className="sheet-who">
            {sheet.size && <span>{t("sheet.size", { size: sheet.size })}</span>}
            {Boolean(sheet.ac_vs_larger) && (
              <span>{t("sheet.acVsLarger", { bonus: signed(sheet.ac_vs_larger ?? 0) })}</span>
            )}
          </p>
        )}
      </header>

      {abilities.length > 0 && (
        <ul className="sheet-abilities" aria-label={t("sheet.abilities")}>
          {abilities.map((a) => (
            <li key={a}>
              <span className="ability">{t(`ability.${a}`)}</span>
              <span className="score">{String(scores[a])}</span>
            </li>
          ))}
        </ul>
      )}

      <SheetStats character={character} />
      {character.xp_progress?.length ? <XpProgressLine rows={character.xp_progress} /> : null}

      {(state.conditions.length > 0 || state.effects.length > 0) && (
        <p className="sheet-conditions">
          {state.conditions.map((c) => (
            <span key={c} className="tag">
              {c}
            </span>
          ))}
          {state.effects.map((e) => (
            <span key={e.name} className="tag effect">
              {t("sheet.effectRounds", { name: e.name, rounds: String(e.duration) })}
            </span>
          ))}
        </p>
      )}

      <div className="sheet-columns">
        <section>
          <h4>
            <abbr title={t("sheet.savesExplain")}>{t("sheet.saves")}</abbr>
          </h4>
          {Object.keys(sheet.saves).length === 0 ? (
            <p className="placeholder">{t("sheet.noSaves")}</p>
          ) : (
            <table className="sheet-table">
              <tbody>
                {/* In the sheet's own order: the ruleset's, as play fills them in. */}
                {Object.keys(sheet.saves).map((s) => (
                  <tr key={s}>
                    <td>{saveName(t, s)}</td>
                    <td className="num">{sheet.saves[s]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section>
          <h4>{t("sheet.attacks")}</h4>
          {sheet.attacks.length === 0 ? (
            <p className="placeholder">{t("sheet.noAttacks")}</p>
          ) : (
            <table className="sheet-table">
              <thead>
                <tr>
                  <th>{t("sheet.attackName")}</th>
                  <th>{t("sheet.attackRate")}</th>
                  <th>{t("sheet.attackSpeed")}</th>
                  <th>{t("sheet.attackThac0")}</th>
                  <th>{t("sheet.attackDamage")}</th>
                </tr>
              </thead>
              <tbody>
                {sheet.attacks.map((a) => (
                  <tr key={a.name}>
                    <td>{a.name}</td>
                    <td className="num">{a.attacks}</td>
                    <td className="num">{a.speed ?? ""}</td>
                    <td className="num" title={a.thac0_worked ? thac0Parts(t, a.thac0_worked.parts) : undefined}>
                      {a.thac0 ?? a.thac0_worked?.value ?? sheet.thac0}
                    </td>
                    <td>{`${a.damage_sm} / ${a.damage_l}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {sheet.weapon && <p className="sheet-weapon">{t("sheet.inHand", { weapon: sheet.weapon })}</p>}
        </section>
      </div>

      {(weaponProfs.length > 0 || nwps.length > 0) && (
        <div className="sheet-columns">
          {weaponProfs.length > 0 && (
            <section>
              <h4 id={`${headingId}-weapon-profs`}>{t("sheet.weaponProfs")}</h4>
              <ul className="sheet-items" aria-labelledby={`${headingId}-weapon-profs`}>
                {weaponProfs.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </section>
          )}
          {nwps.length > 0 && (
            <section>
              <h4 id={`${headingId}-nwps`}>{t("sheet.nwps")}</h4>
              <ul className="sheet-items" aria-labelledby={`${headingId}-nwps`}>
                {nwps.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {(skills.length > 0 || naturalAbilities.length > 0) && (
        <div className="sheet-columns">
          {skills.length > 0 && (
            <section>
              <h4>{t("sheet.skills")}</h4>
              <table className="sheet-table">
                <tbody>
                  {skills.map(([skill, value]) => (
                    <tr key={skill}>
                      <td>{skillName(t, skill)}</td>
                      <td className="num">{t("sheet.percent", { value: String(value) })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
          {naturalAbilities.length > 0 && (
            <section>
              <h4 id={`${headingId}-natural`}>{t("sheet.naturalAbilities")}</h4>
              <ul className="sheet-items" aria-labelledby={`${headingId}-natural`}>
                {naturalAbilities.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      <section>
        <h4>{t("sheet.inventory")}</h4>
        {encumbrance && (
          <p className={`encumbrance band-${encumbrance.band}`}>
            {t("sheet.encumbrance", {
              band: t(`band.${encumbrance.band}`),
              total: String(encumbrance.total_lb),
              movement: String(encumbrance.movement),
            })}
          </p>
        )}
        {inventory.length === 0 ? (
          <p className="placeholder">{t("sheet.noInventory")}</p>
        ) : (
          <ul className="sheet-items">
            {inventory.map((item) => (
              <li key={item.name}>
                <span>{item.qty === 1 ? item.name : t("sheet.item", { qty: String(item.qty), name: item.name })}</span>
                {item.weight_lb !== null && (
                  <span className="row-meta">{t("sheet.weight", { weight: String(item.weight_lb) })}</span>
                )}
                {item.notes && <span className="row-meta">{item.notes}</span>}
                {item.dm_notes && (
                  <span className="row-meta for-the-dm" data-testid="item-dm-notes">
                    {t("sheet.forTheDm")}: {item.dm_notes}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {hasSpells && (
        <section>
          <h4>{t("sheet.spells")}</h4>
          <h5 id={`${headingId}-memorized`}>{t("sheet.memorized")}</h5>
          {memorized.length === 0 ? (
            <p className="placeholder">{t("sheet.noMemorized")}</p>
          ) : (
            <ul className="sheet-spells" aria-labelledby={`${headingId}-memorized`}>
              {memorized.map((spell, n) => (
                <li key={`${spell.name}-${n}`} className={spell.cast ? "cast" : undefined}>
                  {spell.cast ? (
                    <>
                      <s>{spell.name}</s>
                      <span className="row-meta">{` (${t("sheet.cast")})`}</span>
                    </>
                  ) : (
                    spell.name
                  )}
                </li>
              ))}
            </ul>
          )}
          {spellLevels.length > 0 && (
            <table className="sheet-table">
              <thead>
                <tr>
                  <th />
                  <th>{t("sheet.slots")}</th>
                  <th>{t("sheet.default")}</th>
                  {known && <th>{t("sheet.known")}</th>}
                </tr>
              </thead>
              <tbody>
                {spellLevels.map((level) => (
                  <tr key={level}>
                    <td>{t("sheet.spellLevel", { level })}</td>
                    <td className="num">{sheet.spell_slots[level] ?? 0}</td>
                    <td>{(loadout[level] ?? []).join(", ")}</td>
                    {known && <td>{(known[level] ?? []).join(", ")}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

      {sheet.background && (
        <section>
          <h4>{t("sheet.background")}</h4>
          <p className="sheet-background">{sheet.background}</p>
        </section>
      )}

      {(story || disposition !== undefined) && (
        <section className="sheet-dm">
          <h4>{t("sheet.forTheDm")}</h4>
          {disposition !== undefined && (
            <p>
              {t("sheet.disposition")} <strong>{signed(disposition)}</strong>
            </p>
          )}
          {/* renderMarkdown escapes the text before it makes its few tags. */}
          {story && <div className="sheet-story" dangerouslySetInnerHTML={{ __html: renderMarkdown(story) }} />}
        </section>
      )}
    </article>
  );
}

/** HP, AC, THAC0, XP and movement, the numbers with the reader's separators; HP's "61 / 62" never breaks. AC, THAC0
 * and Move say what they are on hover, for a player new to the game (DEL-266); Move is the loaded rate, the unloaded one
 * under it, in small type, when the load slows the character. */
function SheetStats({ character: { sheet, state, encumbrance } }: { character: Character }) {
  const t = useT();
  const number = new Intl.NumberFormat(useLanguage());
  return (
    <dl className="sheet-stats">
      <div>
        <dt>{t("sheet.hp")}</dt>
        <dd className="nowrap">{`${number.format(state.hp)} / ${number.format(sheet.hp_max)}`}</dd>
      </div>
      <div>
        <dt>
          <abbr title={t("sheet.acExplain")}>{t("sheet.ac")}</abbr>
        </dt>
        <dd>{sheet.ac}</dd>
      </div>
      <div>
        <dt>
          <abbr title={t("sheet.thac0Explain")}>{t("sheet.thac0")}</abbr>
        </dt>
        <dd>{sheet.thac0}</dd>
      </div>
      <div>
        <dt>{t("sheet.xp")}</dt>
        <dd>{number.format(state.xp)}</dd>
      </div>
      <div>
        <dt>
          <abbr title={t("sheet.movementExplain")}>{t("sheet.movement")}</abbr>
        </dt>
        <dd>
          {encumbrance && encumbrance.movement !== sheet.movement_rate ? (
            <>
              {encumbrance.movement}
              <span className="sheet-stat-note">
                {t("sheet.moveUnloaded", { base: String(sheet.movement_rate) })}
              </span>
            </>
          ) : (
            sheet.movement_rate
          )}
        </dd>
      </div>
    </dl>
  );
}

/** Each class's XP share against what its next level needs: "Fighter 2,600 / 4,000 · Mage 2,600 / 5,000". */
function XpProgressLine({ rows }: { rows: XpProgress[] }) {
  const t = useT();
  const number = new Intl.NumberFormat(useLanguage());
  return (
    <p className="sheet-xp-progress" data-testid="xp-progress">
      {rows
        .map(
          (row) =>
            `${row.class} ${number.format(row.xp)}` +
            (row.xp_next === null ? "" : ` / ${number.format(row.xp_next)}`) +
            (row.ready ? ` (${t("sheet.levelReady")})` : ""),
        )
        .join(" · ")}
    </p>
  );
}
