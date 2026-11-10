import { useId, useState } from "react";
import { useT, type Translate } from "../i18n";
import { TERRAIN_CLASSES } from "./brush";
import { OUTSIDE, type ClusterReading, type Doubt, type Reading } from "./importApi";
import styles from "./WorldImport.module.css";

/** What the review sends: colours mapped, doubts decided one by one, or a whole kind at once. */
export type ReviewBody = {
  clusters?: Record<string, string>;
  decisions?: Record<string, string>;
  kinds?: Record<string, string>;
};

/** A colour's doubt is decided by its terrain picker, not in the list of doubts. */
const COLOUR_DOUBT = "cluster-unmapped";

/** The choices the review has words for; anything else the server offers is shown as it is. */
const CHOICES = new Set(["place", "river-name", "region-name", "keep", "drop", "reverse", "sea", "lake"]);
const KINDS = new Set([
  "water-kind-guessed",
  "river-flow-guessed",
  "label-unpaired",
  "symbol-unlabelled",
  "label-uncertain",
  "kind-guessed",
  "cell-mixed",
  "river-no-mouth",
]);

/** What a river's end runs into, as the reader names it (`RiverTrace.ends`). */
const WATERS = new Set(["sea", "lake", "river"]);

/** A choice in words: the review's own, a terrain (a mixed cell's), or as the server offers it. */
function choiceLabel(t: Translate, choice: string): string {
  if (CHOICES.has(choice)) return t(`worldReview.choice.${choice}`);
  if (choice === OUTSIDE) return t("worldReview.outside");
  if ((TERRAIN_CLASSES as readonly string[]).includes(choice)) return t(`worldMapEditor.terrain.${choice}`);
  return choice;
}

/**
 * What a doubt was read as, in words (DEL-94): a mixed cell's colour by its swatch and number, as the colours below
 * name it; a guessed river by which way it flows, "from the lake to the sea"; anything else by its choice's label.
 */
function ReadAs({ doubt, clusters }: { doubt: Doubt; clusters: ClusterReading[] }) {
  const t = useT();
  const cluster = doubt.kind === "cell-mixed" ? clusters.find((c) => String(c.id) === doubt.reading) : undefined;
  if (cluster) {
    return (
      <p className="row-meta">
        <span className={styles.inlineSwatch} style={{ background: hex(cluster.colour) }} aria-hidden="true" />{" "}
        {t("worldReview.reading", { reading: t("worldReview.colourN", { n: String(cluster.id + 1) }) })}
      </p>
    );
  }
  const flows = doubt.data?.flows;
  if (doubt.kind === "river-flow-guessed" && Array.isArray(flows) && flows.length === 2 && flows.every((w) => WATERS.has(w))) {
    const flow = t("worldReview.flow", { from: t(`worldReview.flowFrom.${flows[0]}`), to: t(`worldReview.flowTo.${flows[1]}`) });
    return <p className="row-meta">{t("worldReview.reading", { reading: flow })}</p>;
  }
  return <p className="row-meta">{t("worldReview.reading", { reading: choiceLabel(t, doubt.reading) })}</p>;
}
const kindLabel = (t: Translate, kind: string) => (KINDS.has(kind) ? t(`worldReview.kind.${kind}`) : kind);

/** A doubt's choices: its alternatives, then Keep and Drop. */
export function choicesOf(doubt: Doubt): string[] {
  return [...new Set([...doubt.alternatives, "keep", "drop"])];
}

/** The choices every open doubt of a kind offers, in the first one's order. */
export function sharedChoices(doubts: Doubt[]): string[] {
  const open = doubts.filter((d) => !d.resolved);
  if (open.length === 0) return [];
  const [first, ...rest] = open.map(choicesOf);
  return first.filter((c) => rest.every((choices) => choices.includes(c)));
}

/** A colour still to map: neither a terrain nor outside the map. */
export const isUnmapped = (cluster: ClusterReading) => !cluster.terrain || cluster.terrain === ".";

/** The doubts by kind, in the server's order: the kinds as they first come, each with its doubts as they come. */
function byKind(doubts: Doubt[]): [string, Doubt[]][] {
  const groups = new Map<string, Doubt[]>();
  for (const doubt of doubts) {
    if (doubt.kind === COLOUR_DOUBT) continue;
    const group = groups.get(doubt.kind) ?? [];
    group.push(doubt);
    groups.set(doubt.kind, group);
  }
  return [...groups];
}

const hex = ([r, g, b]: [number, number, number]) =>
  `#${[r, g, b].map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0")).join("")}`;

/**
 * The review of a map read from a picture: the doubtful readings first, by kind in the server's order, each with its
 * reading and one decision (its alternatives, Keep or Drop), and each kind with **Decide all of this kind**; then the
 * colours, each with a terrain picker showing Claude's suggestion, whose last choice is **Outside the map**. Accept
 * waits, with its reason, until every colour has a terrain or is outside the map.
 */
export default function ReviewPanel({
  reading,
  onReview,
  onAccept,
  onSelect,
  busy,
}: {
  reading: Reading;
  onReview: (body: ReviewBody) => void;
  onAccept: () => void;
  onSelect: (doubt: Doubt) => void;
  busy: boolean;
}) {
  const t = useT();
  const groups = byKind(reading.doubts);
  const unmapped = reading.clusters.filter(isUnmapped).length;

  return (
    <div className={styles.panel}>
      <h2>{t("worldReview.doubts")}</h2>
      {groups.length === 0 ? (
        <p className="placeholder">{t("worldReview.noDoubts")}</p>
      ) : (
        groups.map(([kind, doubts]) => (
          <KindGroup
            key={kind}
            kind={kind}
            doubts={doubts}
            clusters={reading.clusters}
            busy={busy}
            onReview={onReview}
            onSelect={onSelect}
          />
        ))
      )}

      <h2>{t("worldReview.colours")}</h2>
      <p className="row-meta">{t("worldReview.coloursLede")}</p>
      <ul className="rows">
        {reading.clusters.map((cluster) => (
          <ColourRow key={cluster.id} cluster={cluster} busy={busy} onReview={onReview} />
        ))}
      </ul>

      <div className="actions">
        <button type="button" className="primary" disabled={busy || unmapped > 0} onClick={onAccept}>
          {t("worldReview.accept")}
        </button>
      </div>
      {unmapped > 0 && <p className="row-meta">{t("worldReview.acceptWaits")}</p>}
    </div>
  );
}

function KindGroup({
  kind,
  doubts,
  clusters,
  busy,
  onReview,
  onSelect,
}: {
  kind: string;
  doubts: Doubt[];
  clusters: ClusterReading[];
  busy: boolean;
  onReview: (body: ReviewBody) => void;
  onSelect: (doubt: Doubt) => void;
}) {
  const t = useT();
  const id = useId();
  const shared = sharedChoices(doubts);
  const [all, setAll] = useState("");
  const chosen = shared.includes(all) ? all : (shared[0] ?? "");

  return (
    <section role="group" aria-labelledby={`${id}-heading`} className={styles.kind}>
      <h3 id={`${id}-heading`}>{t("worldReview.kindCount", { kind: kindLabel(t, kind), count: String(doubts.length) })}</h3>
      {shared.length > 0 && (
        <div className="inline-form">
          <div className="field">
            <label htmlFor={`${id}-all`}>{t("worldReview.forAll")}</label>
            <select id={`${id}-all`} value={chosen} onChange={(e) => setAll(e.target.value)}>
              {shared.map((c) => (
                <option key={c} value={c}>
                  {choiceLabel(t, c)}
                </option>
              ))}
            </select>
          </div>
          <button type="button" disabled={busy} onClick={() => onReview({ kinds: { [kind]: chosen } })}>
            {t("worldReview.decideAll")}
          </button>
        </div>
      )}
      <ul className="rows">
        {doubts.map((doubt) => (
          <li key={doubt.id} data-doubt={doubt.id} className={doubt.resolved ? styles.resolved : undefined}>
            <button type="button" className="link" onClick={() => onSelect(doubt)}>
              {doubt.message}
            </button>
            {doubt.reading && <ReadAs doubt={doubt} clusters={clusters} />}
            {doubt.resolved ? (
              <p className="row-meta">
                {t("worldReview.decided", { choice: choiceLabel(t, doubt.choice ?? "keep") })}
              </p>
            ) : (
              <div className={`actions ${styles.choices}`}>
                {choicesOf(doubt).map((choice) => (
                  <button
                    key={choice}
                    type="button"
                    disabled={busy}
                    onClick={() => onReview({ decisions: { [doubt.id]: choice } })}
                  >
                    {choiceLabel(t, choice)}
                  </button>
                ))}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ColourRow({
  cluster,
  busy,
  onReview,
}: {
  cluster: ClusterReading;
  busy: boolean;
  onReview: (body: ReviewBody) => void;
}) {
  const t = useT();
  const id = useId();
  const label = t("worldReview.colourN", { n: String(cluster.id + 1) });
  const value = isUnmapped(cluster) ? "" : (cluster.terrain ?? "");
  return (
    <li data-cluster={String(cluster.id)} aria-label={label} className={styles.colour}>
      <span className={styles.swatch} style={{ background: hex(cluster.colour) }} aria-hidden="true" />
      <div className="field">
        <label htmlFor={`${id}-terrain`}>
          {label} · {t("worldReview.cells", { count: String(cluster.cells.length) })}
        </label>
        <select
          id={`${id}-terrain`}
          value={value}
          disabled={busy}
          onChange={(e) => e.target.value && onReview({ clusters: { [String(cluster.id)]: e.target.value } })}
        >
          <option value="">{t("worldReview.noTerrain")}</option>
          {TERRAIN_CLASSES.map((terrain) => (
            <option key={terrain} value={terrain}>
              {t(`worldMapEditor.terrain.${terrain}`)}
            </option>
          ))}
          <option value={OUTSIDE}>{t("worldReview.outside")}</option>
        </select>
      </div>
      {cluster.suggestion && (
        <p className="row-meta">
          {t("worldReview.suggested", {
            terrain: cluster.suggestion === OUTSIDE ? t("worldReview.outside") : t(`worldMapEditor.terrain.${cluster.suggestion}`),
          })}
        </p>
      )}
    </li>
  );
}
