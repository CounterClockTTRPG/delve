import { useEffect, useState } from "react";
import { Button } from "../editor/Primitives";
import { useT } from "../i18n";
import type { Layer, Units } from "./api";
import { MILES_TO_KM } from "./crs";
import type { GeoDocFeature } from "./editorApi";
import styles from "./WorldMapEditor.module.css";

/** The server's kinds per layer (`delve.maps.geo.terrain`); a region's kind is free. */
export const PLACE_KINDS = ["city", "town", "village", "castle", "ruin", "dungeon", "port", "other"] as const;
export const ROUTE_KINDS = ["road", "track", "trail"] as const;
export const WATER_KINDS = ["river", "lake", "sea"] as const;

/** The kinds a feature may take: a river is a line, a lake or a sea an area. Null for a region's free kind. */
export function kindsOf(layer: Layer, geometryType: string): readonly string[] | null {
  if (layer === "places") return PLACE_KINDS;
  if (layer === "routes") return ROUTE_KINDS;
  if (layer === "water") return geometryType === "LineString" ? ["river"] : ["lake", "sea"];
  return null;
}

/** A river with its line turned round: downstream is the line's direction, so this swaps its source and its mouth.
 * Anything else comes back as it was. */
export function reverseFlow(feature: GeoDocFeature): GeoDocFeature {
  if (feature.properties.kind !== "river" || feature.geometry.type !== "LineString") return feature;
  return { ...feature, geometry: { type: "LineString", coordinates: [...feature.geometry.coordinates].reverse() } };
}

/** A text field that tells its change once it is left (or on Enter), so that undo takes a word, not a letter. */
function TextField({
  id,
  label,
  hint,
  value,
  multiline,
  autoFocus,
  onCommit,
}: {
  id: string;
  label: string;
  hint?: string;
  value: string;
  multiline?: boolean;
  autoFocus?: boolean;
  onCommit: (value: string) => void;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  const commit = () => {
    if (text !== value) onCommit(text);
  };
  return (
    <div className={styles.formField}>
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea id={id} rows={3} value={text} onChange={(e) => setText(e.target.value)} onBlur={commit} />
      ) : (
        <input
          id={id}
          autoFocus={autoFocus}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
          }}
        />
      )}
      {hint ? <span className={styles.hint}>{hint}</span> : null}
    </div>
  );
}

/**
 * The selected feature's fields: its name, its kind (the kinds of its layer), what the players read once they know it,
 * the DM's notes, and whether it is hidden. A river also has its navigable stretch, in the map's units, whether it is a
 * barrier, and Reverse the flow. Each change goes to `onChange` as the whole new feature.
 */
export default function FeatureForm({
  feature,
  units,
  onChange,
  onRemove,
}: {
  feature: GeoDocFeature;
  units: Units;
  onChange: (feature: GeoDocFeature) => void;
  onRemove: () => void;
}) {
  const t = useT();
  const p = feature.properties;
  const set = (props: Partial<GeoDocFeature["properties"]>) =>
    onChange({ ...feature, properties: { ...p, ...props } });
  const kinds = kindsOf(p.layer, feature.geometry.type);
  const id = (field: string) => `feature-${feature.id}-${field}`;
  const unitKm = units === "miles" ? MILES_TO_KM : 1;
  const navigable = typeof p.navigable_km === "number" ? String(Math.round((p.navigable_km / unitKm) * 10) / 10) : "";
  const kindLabel = (kind: string) =>
    p.layer === "places" ? t(`worldMap.kind.${kind}`) : t(`worldMapEditor.kind.${kind}`);

  return (
    <form className={styles.form} aria-label={t("worldMapEditor.feature")} onSubmit={(e) => e.preventDefault()}>
      <h2 className={styles.formTitle}>{t(`worldMapEditor.layer.${p.layer}`)}</h2>
      <TextField
        id={id("name")}
        label={t("worldMapEditor.name")}
        value={p.name}
        // A feature just drawn has no name yet: it is what the organiser types next.
        autoFocus={!p.name}
        onCommit={(name) => set({ name })}
      />
      <div className={styles.formField}>
        <label htmlFor={id("kind")}>{t("world.kind")}</label>
        {kinds ? (
          <select id={id("kind")} value={p.kind} onChange={(e) => set({ kind: e.target.value })}>
            {kinds.map((kind) => (
              <option key={kind} value={kind}>
                {kindLabel(kind)}
              </option>
            ))}
          </select>
        ) : (
          <input id={id("kind")} value={p.kind} onChange={(e) => set({ kind: e.target.value })} />
        )}
      </div>
      <TextField
        id={id("description")}
        label={t("worldMapEditor.description")}
        hint={t("worldMapEditor.descriptionHint")}
        value={p.description}
        multiline
        onCommit={(description) => set({ description })}
      />
      <TextField
        id={id("dm_notes")}
        label={t("worldMapEditor.dmNotes")}
        hint={t("worldMapEditor.dmNotesHint")}
        value={p.dm_notes}
        multiline
        onCommit={(dm_notes) => set({ dm_notes })}
      />
      <TextField
        id={id("tags")}
        label={t("worldMapEditor.tags")}
        hint={t("worldMapEditor.tagsHint")}
        value={p.tags.join(", ")}
        onCommit={(tags) =>
          set({
            tags: tags
              .split(",")
              .map((tag) => tag.trim())
              .filter(Boolean),
          })
        }
      />
      <div className={styles.check}>
        <input
          id={id("hidden")}
          type="checkbox"
          checked={p.hidden}
          onChange={(e) => set({ hidden: e.target.checked })}
        />
        <label htmlFor={id("hidden")}>{t("worldMapEditor.hidden")}</label>
      </div>
      {p.kind === "river" && feature.geometry.type === "LineString" ? (
        <>
          <TextField
            id={id("navigable")}
            label={t("worldMapEditor.navigable", { unit: t(`worldMapEditor.units.${units}`) })}
            hint={t("worldMapEditor.navigableHint")}
            value={navigable}
            onCommit={(text) => {
              const value = Number(text.replace(",", "."));
              if (text.trim() === "") set({ navigable_km: undefined });
              else if (Number.isFinite(value) && value >= 0) set({ navigable_km: value * unitKm });
            }}
          />
          <div className={styles.check}>
            <input
              id={id("barrier")}
              type="checkbox"
              checked={Boolean(p.barrier)}
              onChange={(e) => set({ barrier: e.target.checked })}
            />
            <label htmlFor={id("barrier")}>{t("worldMapEditor.barrier")}</label>
          </div>
          <Button type="button" variant="secondary" onClick={() => onChange(reverseFlow(feature))}>
            {t("worldMapEditor.reverseFlow")}
          </Button>
        </>
      ) : null}
      <Button type="button" variant="danger" onClick={onRemove}>
        {t("worldMapEditor.remove")}
      </Button>
    </form>
  );
}
