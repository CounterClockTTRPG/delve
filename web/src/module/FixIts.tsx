import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState, type FormEvent } from "react";
import { EventsContext, NeedsToken, ENTITY_KINDS, type ConversionEvent, type ModuleMapEntry, type ModuleSource } from "../api";
import { useT, type Translate } from "../i18n";
import { stepLine } from "./conversions";
import FixItReview from "./FixItReview";
import styles from "./FixIts.module.css";
import {
  anchorOf,
  closeFixit,
  fixitsKey,
  listFixits,
  rerunFixit,
  sendFixit,
  type FixitAnchor,
  type FixitComment,
} from "./fixits";

/**
 * The module's fix-it comments (table voice and fixes Task F2.3): a comment in plain words, optionally tied to a map,
 * a room, a text or an entity of the module, starts a background job that proposes the change. The list shows each
 * comment with its status; one ready to review opens `FixItReview`, an open one can be closed without running, and a
 * failed or rejected one run again. The list follows the `modules` and `conversion` events.
 */
export default function FixIts({
  moduleId,
  maps,
  source,
}: {
  moduleId: string;
  maps: ModuleMapEntry[];
  source: ModuleSource | undefined;
}) {
  const t = useT();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const comments = useQuery({ queryKey: fixitsKey(moduleId), queryFn: () => listFixits(moduleId) });
  const [text, setText] = useState("");
  const [anchor, setAnchor] = useState("");
  const [reviewing, setReviewing] = useState<string | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: fixitsKey(moduleId), exact: true });

  useEffect(
    () =>
      subscribe({
        modules: (data) => {
          if ((data as { id?: unknown } | null)?.id === moduleId) refresh();
        },
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          const known = client.getQueryData<FixitComment[]>(fixitsKey(moduleId));
          if (event?.id && known?.some((c) => c.conversion_id === event.id)) refresh();
        },
      }),
    [subscribe, client, moduleId], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const send = useMutation({
    mutationFn: () => sendFixit(moduleId, text.trim(), anchorOf(anchor)),
    onSuccess: () => {
      setText("");
      setAnchor("");
      refresh();
    },
  });
  const act = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: refresh });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (text.trim()) send.mutate();
  }

  const failed = [comments.error, send.error, act.error].find((e) => e && !(e instanceof NeedsToken));
  const list = comments.data ?? [];
  return (
    <section className={styles.fixits} aria-labelledby="fixits-title" data-testid="fixits">
      <h2 id="fixits-title">{t("fixit.title")}</h2>
      <p className="hint">{t("fixit.hint")}</p>
      <form className={styles.form} onSubmit={submit}>
        <div className="field">
          <label htmlFor="fixit-text">{t("fixit.comment")}</label>
          <textarea
            id="fixit-text"
            rows={3}
            value={text}
            placeholder={t("fixit.placeholder")}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="fixit-anchor">{t("fixit.anchor")}</label>
          <select id="fixit-anchor" value={anchor} onChange={(e) => setAnchor(e.target.value)}>
            <option value="">{t("fixit.anchor.none")}</option>
            <AnchorOptions maps={maps} source={source} />
          </select>
        </div>
        <button type="submit" className="primary" disabled={send.isPending || !text.trim()}>
          {t("fixit.send")}
        </button>
      </form>
      {failed && (
        <p role="alert" className="notice error">
          {t("fixit.failed", { error: failed.message })}
        </p>
      )}
      {list.length > 0 && (
        <ul className="rows fixit-list" aria-label={t("fixit.list")}>
          {list.map((comment) => (
            <li key={comment.id} className={`row ${styles.comment}`} data-status={comment.status} data-testid="fixit-comment">
              <p className={styles.text}>{comment.text}</p>
              <p className="row-meta">
                <span className="tag">{t(`fixit.status.${comment.status}`)}</span>
                {comment.anchor && <span>{` · ${anchorLabel(t, comment.anchor, source)}`}</span>}
                {comment.author && <span>{` · ${comment.author}`}</span>}
                {comment.status === "working" && comment.job && (
                  <span>{` · ${comment.job.status === "queued" ? t("fixit.queued") : stepLine(t, comment.job)}`}</span>
                )}
                {comment.status === "kept" && comment.revision !== null && (
                  <span>{` · ${t("fixit.keptAs", { revision: String(comment.revision) })}`}</span>
                )}
              </p>
              {comment.status === "failed" && comment.error && (
                <p className="row-meta error">{t("fixit.reason", { error: comment.error })}</p>
              )}
              <div className="actions">
                {comment.status === "review" && comment.conversion_id && (
                  <button type="button" className="primary" onClick={() => setReviewing(comment.conversion_id)}>
                    {t("fixit.review")}
                  </button>
                )}
                {comment.status === "open" && (
                  <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => closeFixit(comment.id))}>
                    {t("fixit.close")}
                  </button>
                )}
                {(comment.status === "failed" || comment.status === "rejected") && (
                  <button type="button" disabled={act.isPending} onClick={() => act.mutate(() => rerunFixit(comment.id))}>
                    {t("fixit.rerun")}
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {reviewing && (
        <FixItReview
          moduleId={moduleId}
          conversionId={reviewing}
          onClose={() => {
            setReviewing(null);
            refresh();
          }}
        />
      )}
    </section>
  );
}

/** The rooms of the module's maps that its texts are keyed to, once each, by map. */
function rooms(source: ModuleSource | undefined): { map: string; node: string; label: string }[] {
  const seen = new Set<string>();
  return (source?.links ?? []).flatMap((link) => {
    const key = `${link.map}/${link.node}`;
    if (!link.node || seen.has(key)) return [];
    seen.add(key);
    return [{ map: link.map, node: link.node, label: link.label || link.node }];
  });
}

function AnchorOptions({ maps, source }: { maps: ModuleMapEntry[]; source: ModuleSource | undefined }) {
  const t = useT();
  const playable = maps.filter((m) => m.role === "map");
  const linked = rooms(source);
  return (
    <>
      {playable.length > 0 && (
        <optgroup label={t("fixit.anchor.maps")}>
          {playable.map((m) => (
            <option key={m.name} value={`map:${m.name}`}>
              {m.name}
            </option>
          ))}
        </optgroup>
      )}
      {linked.length > 0 && (
        <optgroup label={t("fixit.anchor.rooms")}>
          {linked.map((room) => (
            <option key={`${room.map}/${room.node}`} value={`room:${room.map}/${room.node}`}>
              {t("fixit.anchor.room", { label: room.label, map: room.map })}
            </option>
          ))}
        </optgroup>
      )}
      {(source?.texts.length ?? 0) > 0 && (
        <optgroup label={t("fixit.anchor.texts")}>
          {source?.texts.map((text) => (
            <option key={text.id} value={`text:${text.id}`}>
              {text.title}
            </option>
          ))}
        </optgroup>
      )}
      {ENTITY_KINDS.filter((kind) => (source?.entities[kind]?.length ?? 0) > 0).map((kind) => (
        <optgroup key={kind} label={t(`module.tab.${kind}`)}>
          {source?.entities[kind]?.map((record) => (
            <option key={record.id} value={`entity:${kind}/${record.id}`}>
              {record.name}
            </option>
          ))}
        </optgroup>
      ))}
    </>
  );
}

/** What a comment is tied to, in words: "the map caves", "room 2. Hall on caves", a text's title, an entity's name. */
export function anchorLabel(t: Translate, anchor: FixitAnchor, source: ModuleSource | undefined): string {
  if (anchor.kind === "map") return t("fixit.anchor.onMap", { map: anchor.map });
  if (anchor.kind === "room") {
    const room = rooms(source).find((r) => r.map === anchor.map && r.node === anchor.node);
    return t("fixit.anchor.room", { label: room?.label ?? anchor.node, map: anchor.map });
  }
  if (anchor.kind === "text") return source?.texts.find((text) => text.id === anchor.text_id)?.title ?? anchor.text_id;
  return source?.entities[anchor.entity_kind]?.find((r) => r.id === anchor.entity_id)?.name ?? anchor.entity_id;
}
