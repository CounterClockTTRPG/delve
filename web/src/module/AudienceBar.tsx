import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { NeedsToken, queryKeys, setAudiences, type Audience, type EntityKind } from "../api";
import { useT } from "../i18n";
import styles from "./AudienceBar.module.css";

/** An item's ref for the bulk audience route: `text:<id>`, `npc:<id>` for the entity kind `npcs`, or `asset:<id>`. */
export const textRef = (id: string) => `text:${id}`;
export const entityRef = (kind: EntityKind, id: string) => `${kind.slice(0, -1)}:${id}`;
export const assetRef = (id: string) => `asset:${id}`;

export interface Chosen {
  /** The refs ticked, of those still in the list, in the list's order. */
  refs: string[];
  has: (ref: string) => boolean;
  toggle: (ref: string) => void;
  /** Ticks every ref of the list, or none. */
  all: (on: boolean) => void;
  clear: () => void;
}

/** The ticks of one list, whose items have these refs. A ref that leaves the list leaves the ticks. */
export function useChosen(refs: string[]): Chosen {
  const [ticked, setTicked] = useState<ReadonlySet<string>>(new Set());
  const has = (ref: string) => ticked.has(ref);
  return {
    refs: refs.filter(has),
    has,
    toggle: (ref) =>
      setTicked((now) => {
        const next = new Set(now);
        if (!next.delete(ref)) next.add(ref);
        return next;
      }),
    all: (on) => setTicked(new Set(on ? refs : [])),
    clear: () => setTicked(new Set()),
  };
}

/** A row's tick, named by the row. */
export function ChooseBox({ chosen, itemRef, name }: { chosen: Chosen; itemRef: string; name: string }) {
  const t = useT();
  return (
    <input
      type="checkbox"
      className={styles.box}
      aria-label={t("module.choose.one", { name })}
      checked={chosen.has(itemRef)}
      onChange={() => chosen.toggle(itemRef)}
    />
  );
}

/** A list row with its tick before it. */
export function ChooseRow({ children, ...box }: { chosen: Chosen; itemRef: string; name: string; children: ReactNode }) {
  return (
    <span className={styles.row}>
      <ChooseBox {...box} />
      {children}
    </span>
  );
}

/** "Select all", for a list's header. */
export function ChooseAll({ chosen, count }: { chosen: Chosen; count: number }) {
  const t = useT();
  if (count === 0) return null;
  return (
    <label className={styles.all}>
      <input
        type="checkbox"
        checked={chosen.refs.length === count}
        ref={(box) => {
          if (box) box.indeterminate = chosen.refs.length > 0 && chosen.refs.length < count;
        }}
        onChange={(e) => chosen.all(e.target.checked)}
      />
      {t("module.choose.all")}
    </label>
  );
}

/**
 * The chosen items' audience (E6): "N chosen", with For the players and DM only. One request sets them all, or none;
 * then the module's source is read again and `onDone` clears the ticks. Nothing shows while nothing is chosen.
 */
export default function AudienceBar({ selected, onDone, moduleId }: { selected: string[]; onDone: () => void; moduleId: string }) {
  const t = useT();
  const client = useQueryClient();
  const set = useMutation({
    mutationFn: (audience: Audience) => setAudiences(moduleId, selected, audience),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.moduleSource(moduleId), exact: true });
      onDone();
    },
  });
  if (selected.length === 0) return null;
  const failed = set.error;
  return (
    <div role="region" aria-label={t("module.choose.bar")} className={styles.bar}>
      <span className={styles.count}>{t("module.choose.count", { count: String(selected.length) })}</span>
      <button type="button" disabled={set.isPending} onClick={() => set.mutate("player")}>
        {t("module.choose.players")}
      </button>
      <button type="button" disabled={set.isPending} onClick={() => set.mutate("gm")}>
        {t("module.choose.dm")}
      </button>
      {failed && !(failed instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("module.changeFailed", { error: failed.message })}
        </p>
      )}
    </div>
  );
}
