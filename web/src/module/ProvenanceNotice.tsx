import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import {
  EventsContext,
  NeedsToken,
  attachmentUrl,
  listConversions,
  queryKeys,
  runningConversionOf,
  type Conversion,
  type ConversionEvent,
} from "../api";
import { useT } from "../i18n";
import ConversionProgress from "./ConversionProgress";
import { startBookMap } from "./mapDrafts";
import styles from "./ProvenanceNotice.module.css";

/** The first line of a map the conversion sketched from a room key (`runner.SKETCHED`). */
const SKETCHED = "# Sketched from the room key: an invented layout.";
/** The first line of a map drawn from the book's page (`sketch.FROM_BOOK`), followed by ` asset:<id>.`. */
const FROM_BOOK = "# Drawn from the book's map";
/** The first line of a map drawn from a description (`sketch.DESCRIBED`). */
const DESCRIBED = "# Drawn from a description.";
const BOOK_MAP = /The book's map is asset:([A-Za-z0-9._-]+)\./;
const BOOK_PAGE = /^ asset:([A-Za-z0-9._-]+)\./;
const MAP_PAGE = /^map-page-\d+$/;

export type Provenance = { kind: "sketched" | "book" | "described"; page: string | null };

/** Where a drafted map came from, by its first line, and the attachment of the book's page it names; null for a map drawn by hand. */
export function provenanceOf(source: string): Provenance | null {
  const first = source.split("\n", 1)[0];
  if (first.startsWith(SKETCHED)) return { kind: "sketched", page: BOOK_MAP.exec(first)?.[1] ?? null };
  if (first.startsWith(FROM_BOOK)) {
    return { kind: "book", page: BOOK_PAGE.exec(first.slice(FROM_BOOK.length))?.[1] ?? null };
  }
  if (first.startsWith(DESCRIBED)) return { kind: "described", page: null };
  return null;
}

const WORDS = { sketched: "module.map.sketched", book: "module.map.fromBook", described: "module.map.described" } as const;

/**
 * The one-line notice of a drafted map: where its layout came from, then the book's page when it names one, and,
 * for a sketch given its map's name, the offer to draw it from the book's map page (plan 7 Task 13). With
 * `onShowPage` the page is a toggle (the map editor shows it beside the canvas); without, a link to the picture.
 * A drawing that runs for this map, also one a PDF conversion started once it made the module, shows its progress.
 */
export default function ProvenanceNotice({
  moduleId,
  source,
  mapName,
  onShowPage,
  pageShown = false,
  className,
}: {
  moduleId: string;
  source: string;
  mapName?: string;
  onShowPage?: (shown: boolean) => void;
  pageShown?: boolean;
  className?: string;
}) {
  const t = useT();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const [started, setStarted] = useState<Conversion | null>(null);
  const provenance = provenanceOf(source);
  const page = provenance?.page ?? null;
  const drawable = Boolean(provenance?.kind === "sketched" && page && mapName && MAP_PAGE.test(page));
  const conversions = useQuery({ queryKey: queryKeys.conversions, queryFn: listConversions, enabled: drawable });
  const known = conversions.data;
  // A job this list doesn't hold yet (the drawing a conversion starts at its end) is fetched when it is first heard.
  useEffect(
    () =>
      drawable
        ? subscribe({
            conversion: (data) => {
              const event = data as ConversionEvent | null;
              if (event && !known?.some((c) => c.id === event.id)) {
                client.invalidateQueries({ queryKey: queryKeys.conversions });
              }
            },
          })
        : undefined,
    [subscribe, client, drawable, known],
  );
  const runningHere = known?.find(
    (c) =>
      c.kind === "book-map" && c.status === "running" && c.target?.module_id === moduleId && c.target?.name === mapName,
  );
  const drawing = started ?? runningHere ?? null;
  const draw = useMutation({
    mutationFn: () => startBookMap(moduleId, mapName ?? "", page ?? ""),
    onSuccess: setStarted,
    onError: (error) => {
      const running = runningConversionOf(error);
      if (running) setStarted(running);
    },
  });
  if (!provenance) return null;
  const words = t(WORDS[provenance.kind]);
  return (
    <div className={["sketch-notice", className].filter(Boolean).join(" ")} role="note">
      <p className={styles.line} title={words}>
        <span className={styles.words}>{words}</span>
        {page &&
          (onShowPage ? (
            <button type="button" className={styles.action} aria-pressed={pageShown} onClick={() => onShowPage(!pageShown)}>
              {pageShown ? t("module.map.hidePage") : t("module.map.showPage")}
            </button>
          ) : (
            <a className={styles.action} href={attachmentUrl(moduleId, page)} target="_blank" rel="noreferrer">
              {t("module.map.showPage")}
            </a>
          ))}
        {drawable && (
          <button
            type="button"
            className={styles.action}
            disabled={draw.isPending || drawing?.status === "running"}
            onClick={() => draw.mutate()}
          >
            {t("mapDrafts.fromBook")}
          </button>
        )}
      </p>
      {draw.error && !(draw.error instanceof NeedsToken) && !runningConversionOf(draw.error) && (
        <p role="alert" className="notice error">
          {t("mapDrafts.startFailed", { error: draw.error.message })}
        </p>
      )}
      {drawing && <ConversionProgress key={drawing.id} conversion={drawing} />}
    </div>
  );
}
