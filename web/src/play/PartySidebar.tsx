import { DndContext, PointerSensor, closestCenter, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { queryKeys, type Portrait as PortraitRecord } from "../api";
import type { Repaintable } from "../campaign/RepaintPortrait";
import Portrait from "../components/Portrait";
import Tip from "../components/Tip";
import { safeStorage } from "../desktop/storage";
import { queuedLine } from "../components/waiting";
import { useLanguage, useT } from "../i18n";
import { TableAvatar } from "../profile/ProfileCard";
import {
  COINS,
  playKeys,
  putMarchingOrder,
  type Coin,
  type DepartedMember,
  type Departure,
  type PartyMember,
  type Seat,
} from "./api";
import PregenPicker from "./PregenPicker";

/**
 * The party in marching order, front first: the portrait (the initial without one), an HP bar, the class and level in
 * shorthand ("F1/MU1") and the conditions. An organiser drags a card to its place, or moves it one place with its
 * arrows (the keyboard's and a phone's way); a tap anywhere else on the card opens the sheet, and the name is its button
 * for the keyboard. Under the name, the player who plays the character, by their own avatar and name (players and
 * tavern Task G3): the portrait stays the character's, and the player's face is never put in its place. Under the
 * party, the PCs who left it, folded: one line per reason ("Fallen: Tansy"), unfolding to their names, each opening the
 * sheet (table voice and fixes Task C3). While a portrait is painting, the card says so (DEL-135); Repaint portrait
 * and Try again are on the character's sheet, not here (owner, 2026-10-28).
 */
export default function PartySidebar({
  campaignId,
  party,
  onOpenSheet,
  canReorder = true,
  portraits = {},
  onPregens,
  pregensBlocked = null,
  levelFit = null,
  pregensBusy = false,
  coin,
  seats = [],
  departed = [],
  sheets = {},
}: {
  campaignId: string;
  party: PartyMember[];
  onOpenSheet: (characterId: string) => void;
  /** The marching order is an organiser's to change; the others see it. */
  canReorder?: boolean;
  /** The portraits by character id, from the sheets. */
  portraits?: Record<string, PortraitRecord | null | undefined>;
  /** The host's: with no party yet, the module's pregens are offered, and asking for them acts with this text. */
  onPregens?: (text: string) => void;
  /** Why the pregens can't be made now: the session hasn't started, or a break (DEL-187). */
  pregensBlocked?: string | null;
  /** For the host: the party's level outside the module's (DEL-187). */
  levelFit?: { min: number; max: number; party: number } | null;
  pregensBusy?: boolean;
  /** The party's purse, which every seat sees; left out, none is shown. */
  coin?: Partial<Record<Coin, number>>;
  /** The seats at the table, for who plays each character. */
  seats?: Seat[];
  /** The PCs who left the party (play state's `departed`). */
  departed?: DepartedMember[];
  /** The sheets by character id, for whether a portrait is painting (DEL-135). */
  sheets?: Record<string, Repaintable | undefined>;
}) {
  const t = useT();
  const client = useQueryClient();
  const reorder = useMutation({
    mutationFn: (order: string[]) => putMarchingOrder(campaignId, order),
    onSettled: () => {
      client.invalidateQueries({ queryKey: playKeys.state(campaignId) });
      client.invalidateQueries({ queryKey: queryKeys.characters(campaignId) });
    },
  });

  // While a new order is on its way the cards show it, so a dropped card stays where it was dropped.
  const order = reorder.isPending ? reorder.variables : null;
  const shown = order ? order.map((id) => party.find((m) => m.id === id)).filter((m) => m !== undefined) : party;

  function move(index: number, by: -1 | 1) {
    reorder.mutate(arrayMove(shown.map((m) => m.id), index, index + by));
  }

  // A drag starts only after the pointer has moved a little, so a click still opens the sheet.
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  function dropped({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id) return;
    const ids = shown.map((m) => m.id);
    reorder.mutate(arrayMove(ids, ids.indexOf(String(active.id)), ids.indexOf(String(over.id))));
  }

  return (
    <section className="party" aria-label={t("play.party")} data-tour="party">
      <h2 className="panel-title">{t("play.party")}</h2>
      {coin && <Purse coin={coin} />}
      {levelFit && <LevelFit campaignId={campaignId} fit={levelFit} />}
      {party.length === 0 ? (
        <>
          <p className="placeholder">{t("play.noParty")}</p>
          {onPregens && <PregenPicker campaignId={campaignId} onAct={onPregens} busy={pregensBusy} blocked={pregensBlocked} />}
        </>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dropped}>
          <SortableContext items={shown.map((m) => m.id)} strategy={verticalListSortingStrategy} disabled={!canReorder || reorder.isPending}>
            <ol className="party-list">
              {shown.map((m, index) => {
                const share = m.hp_max > 0 ? Math.max(0, Math.min(1, m.hp / m.hp_max)) : 0;
                const player = seats.find((s) => s.characters.includes(m.id));
                return (
                  // The name's button takes the keyboard; a tap anywhere on the card reaches here too.
                  <Card key={m.id} id={m.id} movable={canReorder} onClick={() => onOpenSheet(m.id)}>
                    <Portrait campaignId={campaignId} portrait={portraits[m.id] ?? null} name={m.name} size={40} />
                    <div className="party-body">
                      <button type="button" className="party-name">
                        {m.name}
                      </button>
                      {player && (
                        <span className="party-player" onClick={(e) => e.stopPropagation()}>
                          <TableAvatar profile={player.profile} size={18} />
                          <span className="party-player-name">{player.name}</span>
                        </span>
                      )}
                      <div
                        className={`hp-bar${share <= 0.25 ? " low" : ""}`}
                        role="meter"
                        aria-label={t("play.hpOf", { name: m.name })}
                        aria-valuemin={0}
                        aria-valuemax={m.hp_max}
                        aria-valuenow={m.hp}
                      >
                        <span style={{ width: `${share * 100}%` }} />
                      </div>
                      <span className="row-meta">
                        {t("play.hpAc", { hp: String(m.hp), max: String(m.hp_max), ac: String(m.ac) })}
                        {classLevels(m) && ` · ${classLevels(m)}`}
                      </span>
                      {sheets[m.id]?.portrait_painting && (
                        <span className="row-meta" role="status">
                          {queuedLine(t, sheets[m.id]?.portrait_painting) ?? t("sheet.portraitPainting")}
                        </span>
                      )}
                      {m.conditions.length > 0 && (
                        <p className="party-conditions">
                          {m.conditions.map((c) => (
                            <span key={c} className="tag">
                              {c}
                            </span>
                          ))}
                        </p>
                      )}
                    </div>
                    {canReorder && (
                      <div className="party-arrows" onClick={(e) => e.stopPropagation()}>
                        <Tip label={t("play.moveUp", { name: m.name })}>
                          <button
                            type="button"
                            className="icon"
                            aria-label={t("play.moveUp", { name: m.name })}
                            disabled={index === 0 || reorder.isPending}
                            onClick={() => move(index, -1)}
                          >
                            <ArrowUp size={16} aria-hidden="true" />
                          </button>
                        </Tip>
                        <Tip label={t("play.moveDown", { name: m.name })}>
                          <button
                            type="button"
                            className="icon"
                            aria-label={t("play.moveDown", { name: m.name })}
                            disabled={index === shown.length - 1 || reorder.isPending}
                            onClick={() => move(index, 1)}
                          >
                            <ArrowDown size={16} aria-hidden="true" />
                          </button>
                        </Tip>
                      </div>
                    )}
                  </Card>
                );
              })}
            </ol>
          </SortableContext>
        </DndContext>
      )}
      {departed.length > 0 && <Departed departed={departed} onOpenSheet={onOpenSheet} />}
      {reorder.isError && (
        <p className="notice error" role="alert">
          {t("play.orderFailed")}
        </p>
      )}
    </section>
  );
}

// The reasons in the order they are shown, each with its line's key.
const DEPARTURE_LINES: [Departure, string][] = [
  ["died", "departure.fallen"],
  ["retired", "departure.retired"],
  ["left", "departure.left"],
];

/** The PCs who left the party, folded by reason: "Fallen: Tansy, Rook", unfolding to a button per name for its sheet. */
function Departed({ departed, onOpenSheet }: { departed: DepartedMember[]; onOpenSheet: (characterId: string) => void }) {
  const t = useT();
  return (
    <section className="party-departed" aria-label={t("departure.title")}>
      {DEPARTURE_LINES.map(([reason, key]) => {
        const gone = departed.filter((d) => d.departure === reason);
        if (gone.length === 0) return null;
        return (
          <details key={reason} className="party-departure">
            <summary className="row-meta">{t(key, { names: gone.map((d) => d.name).join(", ") })}</summary>
            <ul className="party-departed-list">
              {gone.map((d) => (
                <li key={d.id}>
                  <button type="button" className="link-button" onClick={() => onOpenSheet(d.id)}>
                    {d.name}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </section>
  );
}

// The table's shorthand for a class, as the books write it ("F1", "MU3/T4"); a class without one takes its initial.
const CLASS_SHORT: Record<string, string> = {
  fighter: "F", paladin: "P", ranger: "R", barbarian: "Bb", mage: "MU", wizard: "MU", illusionist: "I", cleric: "C",
  priest: "Pr", druid: "D", thief: "T", bard: "B", sage: "S", alchemist: "A", witch: "W",
};

/** A member's classes and levels in shorthand, in the sheet's order ("F1/MU1"); empty without a class. */
function classLevels(m: Pick<PartyMember, "cls" | "levels">): string {
  const levels = m.levels ?? {};
  const named = (typeof m.cls === "string" ? m.cls.split("/") : []).map((c) => c.trim().toLowerCase()).filter(Boolean);
  const classes = [...new Set([...named, ...Object.keys(levels).map((c) => c.toLowerCase())])];
  return classes
    .map((c) => `${CLASS_SHORT[c] ?? c.charAt(0).toUpperCase()}${levels[c] ?? ""}`)
    .join("/");
}

/** A party card the marching order's drag moves. */
function Card({ id, movable, onClick, children }: { id: string; movable: boolean; onClick: () => void; children: ReactNode }) {
  // Only the pointer drags: the card isn't a control of its own, and its name and arrows are the keyboard's.
  const { listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <li
      ref={setNodeRef}
      className={["party-member", movable && "movable", isDragging && "dragging"].filter(Boolean).join(" ")}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      onClick={onClick}
      {...listeners}
    >
      {children}
    </li>
  );
}

/** The party's purse: its coins, largest first, those it has none of left out ("98 gp · 9 sp · 9 cp"). */
function Purse({ coin }: { coin: Partial<Record<Coin, number>> }) {
  const t = useT();
  const number = new Intl.NumberFormat(useLanguage());
  const held = COINS.filter((c) => (coin[c] ?? 0) > 0);
  return (
    <p className="party-purse" data-testid="party-purse">
      <span className="party-purse-label">{t("play.purse")}</span>{" "}
      {held.length === 0
        ? t("play.purseEmpty")
        : held.map((c, i) => (
            // A coin's number and its name never part at a line break.
            <span key={c}>
              {i > 0 && " · "}
              <span className="coin">{`${number.format(coin[c] ?? 0)} ${t(`coin.${c}`)}`}</span>
            </span>
          ))}
    </p>
  );
}


/** The module's levels against the party's (DEL-187), with an X: dismissed, it stays away in this browser for this
 * campaign while the numbers are the same, and comes back when they change. */
function LevelFit({ campaignId, fit }: { campaignId: string; fit: { min: number; max: number; party: number } }) {
  const t = useT();
  const key = `delve.levelFit.${campaignId}`;
  const shape = `${fit.min}-${fit.max}-${fit.party}`;
  const [dismissed, setDismissed] = useState(() => safeStorage.getItem(key));
  if (dismissed === shape) return null;
  return (
    <p className="notice dismissible-notice" role="status" data-testid="level-fit">
      <span>{t("play.levelFit", { min: String(fit.min), max: String(fit.max), party: String(fit.party) })}</span>
      <button
        type="button"
        className="icon"
        aria-label={t("alerts.dismiss")}
        title={t("alerts.dismiss")}
        onClick={() => {
          safeStorage.setItem(key, shape);
          setDismissed(shape);
        }}
      >
        <X size={16} aria-hidden="true" />
      </button>
    </p>
  );
}
