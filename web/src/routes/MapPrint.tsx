// Print-friendly view modelled on the classic printed module's format:
// map on its own page, then a 3-column room key with bolded heading,
// boxed read-aloud description, plain feature list, and bordered DM
// notes. Drop the page through the browser's Print dialog (Cmd/Ctrl+P)
// to get a clean PDF.
import { useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as api from "../api";
import type { ParsedMap, ParsedRoom } from "../editor/types";
import { useT, type Translate } from "../i18n";
import { useNoLook } from "../looks/looks";
import styles from "./MapPrint.module.css";

interface FeatureEntry {
  name: string;
  description: string;
  dmNotes: string;
}

interface RoomEntry {
  number: string;
  /** Whether the key adds the number: not when the map's labels go bare, nor when the label already starts with it. */
  numbered: boolean;
  label: string;
  description: string;
  dmNotes: string;
  features: FeatureEntry[];
}

interface AnnotatedEntry {
  label: string;
  description: string;
  dmNotes: string;
}

function indexRooms(parsed: ParsedMap | undefined): Map<string, ParsedRoom> {
  const idx = new Map<string, ParsedRoom>();
  if (!parsed) return idx;
  for (const r of Object.values(parsed.rooms)) idx.set(r.name, r);
  for (const layer of parsed.layers) {
    if (layer.hidden) continue;
    for (const r of layer.rooms) {
      if (!idx.has(r.name)) idx.set(r.name, r);
    }
  }
  return idx;
}

function resolveFeatures(
  room: ParsedRoom | undefined,
  parsed: ParsedMap | undefined,
): FeatureEntry[] {
  if (!room || !parsed) return [];
  return room.features.map((fi) => {
    const def = parsed.feature_defs[fi.ref];
    const name = def?.display_name || def?.name || fi.ref;
    const description = (fi.description ?? def?.description ?? "") || "";
    const dmNotes = fi.dm_notes ?? "";
    return { name, description, dmNotes };
  });
}

function collectFromAttrs(
  doc: Document,
  selector: string,
  idAttr: string,
  label: (el: Element, id: string) => string,
): AnnotatedEntry[] {
  // Multiple SVG nodes can carry the same logical id (a corridor renders
  // as both wall and floor paths). Dedupe by id, keeping whichever node
  // first supplies a description / dm-notes string.
  const seen = new Map<string, AnnotatedEntry>();
  for (const el of Array.from(doc.querySelectorAll(selector))) {
    const id = el.getAttribute(idAttr) ?? "";
    if (!id) continue;
    const description = el.getAttribute("data-description") ?? "";
    const dmNotes = el.getAttribute("data-dm-notes") ?? "";
    if (!description && !dmNotes) continue;
    const existing = seen.get(id);
    if (existing) {
      if (!existing.description && description) existing.description = description;
      if (!existing.dmNotes && dmNotes) existing.dmNotes = dmNotes;
      continue;
    }
    seen.set(id, { label: label(el, id), description, dmNotes });
  }
  return Array.from(seen.values());
}

function collectDoors(doc: Document, t: Translate): AnnotatedEntry[] {
  // Doors have no stable id, so we synthesize one from kind + an ordinal
  // index so the print key can list them in source order.
  const entries: AnnotatedEntry[] = [];
  const counts = new Map<string, number>();
  for (const el of Array.from(doc.querySelectorAll("g.door-instance"))) {
    const description = el.getAttribute("data-description") ?? "";
    const dmNotes = el.getAttribute("data-dm-notes") ?? "";
    if (!description && !dmNotes) continue;
    const kind = el.getAttribute("data-door") ?? "door";
    const next = (counts.get(kind) ?? 0) + 1;
    counts.set(kind, next);
    const baseLabel =
      el.getAttribute("data-label") ||
      t("print.door", { kind: `${kind.charAt(0).toUpperCase()}${kind.slice(1)}` });
    entries.push({
      label: `${baseLabel} #${next}`,
      description,
      dmNotes,
    });
  }
  return entries;
}

/** The map's picture and its parse, as the editor renders them: includes resolve against the module's libraries. */
export function useMapPrint(moduleId: string, mapName: string, source: string | undefined) {
  const { data: rendered } = useQuery({
    queryKey: ["render", moduleId, mapName, source],
    queryFn: () => api.dsl.render(source!, moduleId),
    enabled: source !== undefined,
  });

  const { data: parsed } = useQuery({
    queryKey: ["parse", moduleId, mapName, source],
    queryFn: () => api.dsl.parse(source!, moduleId).then((r) => r.map),
    enabled: source !== undefined,
  });

  return { svg: rendered?.svg, parsed };
}

/** A map's page: its read-aloud description and DM notes, then the DM view on a page of its own. */
export function MapPage({ svg, parsed }: { svg: string | undefined; parsed: ParsedMap | undefined }) {
  const t = useT();
  const svgRef = useRef<HTMLDivElement>(null);
  return (
    <>
      {parsed?.map?.description || parsed?.map?.dm_notes ? (
        <section className={styles.introSection}>
          {parsed.map.description ? (
            <p className={styles.readAloud}>{parsed.map.description}</p>
          ) : null}
          {parsed.map.dm_notes ? (
            <div className={styles.dmBox}>
              <span className={styles.dmTag}>{t("editor.dm")}</span>
              <span className={styles.dmText}>{parsed.map.dm_notes}</span>
            </div>
          ) : null}
        </section>
      ) : null}

      <section className={styles.mapSection}>
        <div
          ref={svgRef}
          className={styles.mapHolder}
          dangerouslySetInnerHTML={{ __html: svg ?? "" }}
        />
      </section>
    </>
  );
}

/** A label that already starts with a book's own key, such as "4. " or "C7. ". */
const BOOK_KEY = /^[A-Z]{0,2}\d+[a-z]?\.\s/;

/** A map's key: the rooms in three columns, then the corridors and doors that have notes. */
export function MapKey({ svg, parsed }: { svg: string | undefined; parsed: ParsedMap | undefined }) {
  const t = useT();

  // Numbering and ordering come from the rendered SVG (single source of
  // truth — matches the labels on the map). Description/features/notes
  // come from the parsed model, joined by room name.
  const { rooms, corridors, doors } = useMemo<{
    rooms: RoomEntry[];
    corridors: AnnotatedEntry[];
    doors: AnnotatedEntry[];
  }>(() => {
    if (!svg) return { rooms: [], corridors: [], doors: [] };
    const doc = new DOMParser().parseFromString(
      svg,
      "image/svg+xml",
    );
    const floors = Array.from(doc.querySelectorAll("path.floor[data-number]"));
    const byName = indexRooms(parsed);
    const roomList: RoomEntry[] = floors.map((el) => {
      const roomName = el.getAttribute("data-room") ?? "";
      const room = byName.get(roomName);
      const number = el.getAttribute("data-number") ?? "";
      const label =
        el.getAttribute("data-label") ?? el.getAttribute("data-room") ?? "";
      return {
        number,
        numbered:
          el.getAttribute("data-numbered") !== "false" &&
          !new RegExp(`^${number}\\b`).test(label) &&
          !BOOK_KEY.test(label),
        label,
        description: el.getAttribute("data-description") ?? "",
        dmNotes: el.getAttribute("data-dm-notes") ?? "",
        features: resolveFeatures(room, parsed),
      };
    });
    roomList.sort((a, b) => Number(a.number) - Number(b.number));
    const corridorList = collectFromAttrs(
      doc,
      "[data-corridor]",
      "data-corridor",
      (el, id) => el.getAttribute("data-label") || id,
    );
    const doorList = collectDoors(doc, t);
    return { rooms: roomList, corridors: corridorList, doors: doorList };
  }, [svg, parsed, t]);

  return (
    <>
      <section className={styles.keySection}>
        <h2>{t("print.roomKey")}</h2>
        {rooms.length === 0 ? (
          <p className={styles.muted}>{t("print.noRooms")}</p>
        ) : (
          <ol className={styles.roomList}>
            {rooms.map((r) => (
              <li key={r.number} className={styles.roomItem}>
                <h3 className={styles.roomHeading}>
                  {r.numbered ? (
                    <>
                      <span className={styles.roomNumber}>{r.number}.</span>{" "}
                    </>
                  ) : null}
                  {r.label}
                </h3>
                {r.description ? (
                  <p className={styles.readAloud}>{r.description}</p>
                ) : null}
                {r.features.length > 0 ? (
                  <p className={styles.features}>
                    <span className={styles.featuresLabel}>{t("print.features")}</span>{" "}
                    {r.features.map((f, i) => (
                      <span key={i} className={styles.feature}>
                        {i > 0 ? "; " : ""}
                        <span className={styles.featureName}>{f.name}</span>
                        {f.description ? ` — ${f.description}` : ""}
                      </span>
                    ))}
                    .
                  </p>
                ) : null}
                {r.features.some((f) => f.dmNotes) ? (
                  <ul className={styles.featureNotes}>
                    {r.features
                      .filter((f) => f.dmNotes)
                      .map((f, i) => (
                        <li key={i}>
                          <span className={styles.dmTag}>{t("editor.dm")}</span>
                          <span className={styles.featureName}>{f.name}:</span>{" "}
                          {f.dmNotes}
                        </li>
                      ))}
                  </ul>
                ) : null}
                {r.dmNotes ? (
                  <div className={styles.dmBox}>
                    <span className={styles.dmTag}>{t("editor.dm")}</span>
                    <span className={styles.dmText}>{r.dmNotes}</span>
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </section>

      {corridors.length > 0 ? (
        <section className={styles.auxSection}>
          <h2>{t("print.corridors")}</h2>
          <ul className={styles.auxList}>
            {corridors.map((c, i) => (
              <li key={`c-${i}`} className={styles.auxItem}>
                <span className={styles.auxLabel}>{c.label}</span>
                {c.description ? (
                  <span className={styles.auxBody}>{c.description}</span>
                ) : null}
                {c.dmNotes ? (
                  <div className={styles.dmBox}>
                    <span className={styles.dmTag}>{t("editor.dm")}</span>
                    <span className={styles.dmText}>{c.dmNotes}</span>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {doors.length > 0 ? (
        <section className={styles.auxSection}>
          <h2>{t("print.doors")}</h2>
          <ul className={styles.auxList}>
            {doors.map((d, i) => (
              <li key={`d-${i}`} className={styles.auxItem}>
                <span className={styles.auxLabel}>{d.label}</span>
                {d.description ? (
                  <span className={styles.auxBody}>{d.description}</span>
                ) : null}
                {d.dmNotes ? (
                  <div className={styles.dmBox}>
                    <span className={styles.dmTag}>{t("editor.dm")}</span>
                    <span className={styles.dmText}>{d.dmNotes}</span>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
  );
}

/** `/maps/:moduleId/:mapName/print`: the print view, ported from dungml's MapPrintPage. */
export default function MapPrint() {
  const { moduleId = "", mapName = "" } = useParams();
  const t = useT();
  useNoLook();

  const { data: map } = useQuery({
    queryKey: api.queryKeys.map(moduleId, mapName),
    queryFn: () => api.getMap(moduleId, mapName),
    enabled: !!moduleId && !!mapName,
  });

  const { svg, parsed } = useMapPrint(moduleId, mapName, map?.source);

  useEffect(() => {
    if (map?.name) document.title = t("print.documentTitle", { name: map.name });
  }, [map?.name, t]);

  if (!map) {
    return <div className={styles.loading}>{t("print.loading")}</div>;
  }

  return (
    <div className={`editor-scope ${styles.page}`}>
      <div className={styles.toolbar}>
        <Link to={`/maps/${encodeURIComponent(moduleId)}/${encodeURIComponent(mapName)}`} className={styles.back}>
          {t("print.back")}
        </Link>
        <button
          type="button"
          className={styles.printBtn}
          onClick={() => window.print()}
        >
          {t("print.print")}
        </button>
      </div>

      <header className={styles.header}>
        <h1>{map.name}</h1>
      </header>

      <MapPage svg={svg} parsed={parsed} />
      <MapKey svg={svg} parsed={parsed} />
    </div>
  );
}
