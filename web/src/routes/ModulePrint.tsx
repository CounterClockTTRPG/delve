// The whole module for print (spec §8.3), in the style of the map's print view: a title page, each text as the
// editor shows it, each played map with its key, the NPC and encounter blocks, and the images. DM-only material is
// included, since this is the module itself: the title page says so once, and only what players may see is tagged.
// The texts flow on from one another; each map and each section after them starts a page. The PDF comes from the
// browser's Print dialog.
import { getSchema } from "@tiptap/core";
import { DOMSerializer, Node as PMNode } from "@tiptap/pm/model";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import {
  attachmentUrl,
  getModule,
  getModuleSource,
  queryKeys,
  type EntityRecord,
  type ModuleMapEntry,
  type ModuleSource,
} from "../api";
import { useT, type Translate } from "../i18n";
import { useNoLook } from "../looks/looks";
import { ABILITIES } from "../module/EntityForm";
import { EntityRef, fromMarkdown, moduleTextExtensions } from "../module/MarkdownRoundTrip";
import { readAloud, type Block } from "../module/readAloud";
import { MapKey, MapPage, useMapPrint } from "./MapPrint";
import mapStyles from "./MapPrint.module.css";
import styles from "./ModulePrint.module.css";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const str = (value: unknown) => (value === undefined || value === null ? "" : String(value));

/** The format's ref kinds that name an entity, and the list each one is in. */
const ENTITY_LISTS: Record<string, string> = {
  npc: "npcs",
  encounter: "encounters",
  faction: "factions",
  quest: "quests",
  rumor: "rumors",
  secret: "secrets",
  pregen: "pregens",
};
const NPC_STATS = [
  ["race", "entity.race"],
  ["class", "entity.class"],
  ["level", "entity.level"],
  ["hd", "entity.hd"],
  ["ac", "entity.ac"],
  ["hp", "entity.hp"],
] as const;

/** `intRange`: one number, or {min, max, recommended?}. */
function rangeText(value: unknown): string {
  if (typeof value === "number") return String(value);
  if (!isRecord(value)) return "";
  const [min, max] = [str(value.min), str(value.max)];
  return min && max ? (min === max ? min : `${min}–${max}`) : min || max || str(value.recommended);
}

function authorText(author: unknown, t: Translate): string {
  if (!isRecord(author)) return str(author);
  const role = str(author.role);
  return role ? `${str(author.name)} (${t(`details.role.${role}`)})` : str(author.name);
}

type Schema = ReturnType<typeof getSchema>;

/** The text's Markdown as the editor shows it: its schema, refs as their entity's name, and read-aloud boxed. */
function textHtml(markdown: string, schema: Schema): string {
  const doc = PMNode.fromJSON(schema, fromMarkdown(markdown));
  const fragment = DOMSerializer.fromSchema(schema).serializeFragment(doc.content);
  // The editor's rule (`readAloud`): every quote under a keyed heading, the leading ones under another.
  const children = Array.from(fragment.children);
  const boxed = readAloud(
    children.map((child): Block => {
      const heading = /^H([1-6])$/.exec(child.tagName);
      if (heading) return { heading: { level: Number(heading[1]), text: child.textContent ?? "" } };
      return child.tagName === "BLOCKQUOTE" ? { quote: true } : { other: true };
    }),
  );
  children.forEach((child, i) => boxed[i] && child.classList.add("read-aloud"));
  const holder = document.createElement("div");
  holder.append(fragment);
  return holder.innerHTML;
}

const normalised = (title: string) => title.replace(/\s+/g, " ").trim().toLowerCase();

/** Whether the text's Markdown begins with a `#` heading that is its title, so the part heading would repeat it. */
function headedByTitle(markdown: string, title: string): boolean {
  const heading = /^# +(.*?)(?:\s+\{#[^}]*\})?\s*$/.exec(markdown.trimStart().split("\n", 1)[0]);
  return heading !== null && normalised(heading[1]) === normalised(title);
}

/** `/modules/:moduleId/print`: the whole module, ready for the browser's Print dialog. */
export default function ModulePrint() {
  const { moduleId = "" } = useParams();
  const t = useT();
  useNoLook();
  const module = useQuery({ queryKey: queryKeys.module(moduleId), queryFn: () => getModule(moduleId) });
  const source = useQuery({ queryKey: queryKeys.moduleSource(moduleId), queryFn: () => getModuleSource(moduleId) });
  const entities = source.data?.entities;

  const schema = useMemo(() => {
    const nameOf = (kind: string, id: string) => entities?.[ENTITY_LISTS[kind]]?.find((r) => r.id === id)?.name;
    return getSchema(
      moduleTextExtensions({
        assetUrl: (src) => attachmentUrl(moduleId, src.slice("asset:".length)),
        overrides: [
          EntityRef.extend({
            renderHTML: ({ node }) => {
              const { kind, id } = node.attrs as { kind: string; id: string };
              const name = kind in ENTITY_LISTS ? nameOf(kind, id) : id;
              return ["span", { class: `ref-chip${name === undefined ? " missing" : ""}`, title: `${kind}:${id}` }, name ?? id];
            },
          }),
        ],
      }),
    );
  }, [moduleId, entities]);

  useEffect(() => {
    if (module.data?.title) document.title = t("print.documentTitle", { name: module.data.title });
  }, [module.data?.title, t]);

  const failed = module.error ?? source.error;
  if (failed) {
    return (
      <p role="alert" className="notice error">
        {t("module.loadFailed", { error: failed.message })}
      </p>
    );
  }
  if (!module.data || !source.data) {
    return <div className={mapStyles.loading}>{t("print.loading")}</div>;
  }
  const m = module.data;
  const s = source.data;
  const meta = m.metadata;
  const party = isRecord(meta.party) ? meta.party : {};
  const authors = Array.isArray(meta.authors) ? meta.authors.map((a) => authorText(a, t)).filter(Boolean) : [];
  const facts: [string, string][] = [
    [t("details.authors"), authors.join(", ")],
    [t("details.levels"), rangeText(party.levels)],
    [t("details.size"), rangeText(party.size)],
    [t("details.setting"), str(meta.setting)],
  ];
  const cover = typeof meta.cover === "string" && meta.cover.startsWith("asset:") ? meta.cover.slice(6) : "";
  const maps = m.maps.filter((map) => map.role === "map");
  const npcs = s.entities.npcs ?? [];
  const encounters = s.entities.encounters ?? [];
  const pregens = s.entities.pregens ?? [];
  const images = s.attachments.filter((a) => a.type.startsWith("image/"));

  return (
    <div className={`editor-scope ${mapStyles.page}`}>
      <div className={mapStyles.toolbar}>
        <Link to={`/modules/${encodeURIComponent(moduleId)}`} className={mapStyles.back}>
          {t("modulePrint.back")}
        </Link>
        <button type="button" className={mapStyles.printBtn} onClick={() => window.print()}>
          {t("print.print")}
        </button>
      </div>

      <section data-part="title" className={styles.titlePage}>
        <h1>{m.title}</h1>
        <dl className={styles.facts}>
          {facts
            .filter(([, value]) => value)
            .map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
        </dl>
        {cover && <img className={styles.cover} src={attachmentUrl(moduleId, cover)} alt="" />}
        <p className={styles.note}>{t("print.dmUnlessMarked")}</p>
      </section>

      {s.texts.map((text) => {
        const tag = text.audience === "player" && <PlayersTag />;
        // A text titled as the module (a book's front matter) isn't a second title, nor one its heading repeats.
        const untitled = headedByTitle(text.markdown, text.title) || normalised(text.title) === normalised(m.title);
        return (
          <section key={text.id} data-part="text" className={styles.part}>
            {untitled ? (
              tag && <div>{tag}</div>
            ) : (
              <h2 className={styles.partTitle}>
                {text.title}
                {tag}
              </h2>
            )}
            <div className="text-page markdown" dangerouslySetInnerHTML={{ __html: textHtml(text.markdown, schema) }} />
          </section>
        );
      })}

      {maps.map((map) => (
        <PrintedMap key={map.name} moduleId={moduleId} map={map} />
      ))}

      {npcs.length > 0 && (
        <section data-part="npcs" className={`${styles.part} ${styles.pageBreak}`}>
          <h2 className={styles.partTitle}>{t("module.tab.npcs")}</h2>
          {npcs.map((npc) => (
            <NpcBlock key={npc.id} npc={npc} />
          ))}
        </section>
      )}

      {encounters.length > 0 && (
        <section data-part="encounters" className={`${styles.part} ${styles.pageBreak}`}>
          <h2 className={styles.partTitle}>{t("module.tab.encounters")}</h2>
          {encounters.map((encounter) => (
            <EncounterBlock key={encounter.id} encounter={encounter} npcs={npcs} />
          ))}
        </section>
      )}

      {pregens.length > 0 && (
        <section data-part="pregens" className={`${styles.part} ${styles.pageBreak}`}>
          <h2 className={styles.partTitle}>{t("modulePrint.pregens")}</h2>
          <PregenTable pregens={pregens} />
        </section>
      )}

      {images.length > 0 && (
        <section data-part="images" className={`${styles.part} ${styles.pageBreak}`}>
          <h2 className={styles.partTitle}>{t("modulePrint.images")}</h2>
          {images.map((image) => (
            <figure key={image.id} className={styles.image}>
              <img src={attachmentUrl(moduleId, image.id)} alt="" />
              <figcaption>
                {image.description || image.id}
                {image.audience === "player" && <PlayersTag />}
              </figcaption>
            </figure>
          ))}
        </section>
      )}
    </div>
  );
}

/** A played map as the map's print view prints it: its name, the DM view and its key. */
function PrintedMap({ moduleId, map }: { moduleId: string; map: ModuleMapEntry }) {
  const { svg, parsed } = useMapPrint(moduleId, map.name, map.source);
  return (
    <section data-part="map" className={`${styles.part} ${styles.pageBreak}`}>
      <h2 className={styles.partTitle}>{map.name}</h2>
      <MapPage svg={svg} parsed={parsed} />
      <MapKey svg={svg} parsed={parsed} />
    </section>
  );
}

/** The tag of what players may see; everything else in the print is DM material, as the title page says. */
function PlayersTag() {
  const t = useT();
  return <span className={mapStyles.dmTag}>{t("audience.player")}</span>;
}

function EntityHeading({ record }: { record: EntityRecord }) {
  return (
    <h3 className={`${mapStyles.roomHeading} ${styles.blockTitle}`}>
      {record.name}
      {record.audience === "player" && <PlayersTag />}
    </h3>
  );
}

/** A record's `stats.adnd2e`, or nothing. */
const adnd2e = (record: EntityRecord) => (isRecord(record.stats) && isRecord(record.stats.adnd2e) ? record.stats.adnd2e : {});

function NpcBlock({ npc }: { npc: EntityRecord }) {
  const t = useT();
  const stats = adnd2e(npc);
  const line = NPC_STATS.filter(([key]) => str(stats[key]))
    .map(([key, label]) => `${t(label)} ${str(stats[key])}`)
    .join(" · ");
  return (
    <article className={styles.block}>
      <EntityHeading record={npc} />
      {str(stats.line) && <p className={styles.stats}>{str(stats.line)}</p>}
      {str(npc.summary) && <p>{str(npc.summary)}</p>}
      {line && <p className={styles.stats}>{line}</p>}
      {str(npc.description) && <p className={styles.description}>{str(npc.description)}</p>}
    </article>
  );
}

function EncounterBlock({ encounter, npcs }: { encounter: EntityRecord; npcs: NonNullable<ModuleSource["entities"]["npcs"]> }) {
  const t = useT();
  const fixed = Array.isArray(encounter.fixed) ? encounter.fixed.filter(isRecord) : [];
  const creature = (row: Record<string, unknown>) => {
    const ref = str(row.creature);
    if (ref.startsWith("npc:")) return npcs.find((npc) => npc.id === ref.slice(4))?.name ?? ref.slice(4);
    return ref.startsWith("monster:") ? ref.slice(8) : ref;
  };
  return (
    <article className={styles.block}>
      <EntityHeading record={encounter} />
      {str(adnd2e(encounter).line) && <p className={styles.stats}>{str(adnd2e(encounter).line)}</p>}
      {str(encounter.summary) && <p>{str(encounter.summary)}</p>}
      {(str(encounter.key) || str(encounter.kind)) && (
        <p className={styles.stats}>
          {[
            str(encounter.key) && `${t("entity.where")} ${str(encounter.key)}`,
            str(encounter.kind) && `${t("entity.kind")} ${str(encounter.kind)}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {fixed.length > 0 && (
        <ul className={styles.monsters}>
          {fixed.map((row, i) => (
            <li key={i}>
              {str(row.count) && `${str(row.count)} × `}
              {creature(row)}
              {str(row.notes) && ` — ${str(row.notes)}`}
            </li>
          ))}
        </ul>
      )}
      {str(encounter.description) && <p className={styles.description}>{str(encounter.description)}</p>}
    </article>
  );
}

/** The pregens as the book's roster: one row each, the abilities and hit points from `stats.adnd2e`. */
function PregenTable({ pregens }: { pregens: EntityRecord[] }) {
  const t = useT();
  const heads = [
    t("entity.name"),
    t("entity.race"),
    t("entity.class"),
    t("entity.level"),
    t("entity.alignment"),
    ...ABILITIES.map((key) => t(`entity.ability.${key}`)),
    t("entity.hp"),
    t("entity.gear"),
  ];
  return (
    <table className={styles.pregens}>
      <thead>
        <tr>
          {heads.map((head) => (
            <th key={head}>{head}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {pregens.map((pregen) => {
          const stats = adnd2e(pregen);
          const scores = isRecord(stats.ability_scores) ? stats.ability_scores : {};
          return (
            <tr key={pregen.id}>
              <td>
                {pregen.name}
                {pregen.audience === "player" && <PlayersTag />}
              </td>
              <td>{str(pregen.race)}</td>
              <td>{str(pregen.class)}</td>
              <td>{str(pregen.level)}</td>
              <td>{str(pregen.alignment)}</td>
              {ABILITIES.map((key) => (
                <td key={key}>{str(scores[key])}</td>
              ))}
              <td>{str(stats.hp_max)}</td>
              <td>{Array.isArray(pregen.gear) ? pregen.gear.map(String).join(", ") : str(pregen.gear)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
