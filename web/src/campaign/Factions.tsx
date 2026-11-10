import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import {
  CLOCK_KINDS,
  addClock,
  deleteClock,
  deleteFaction,
  listClocks,
  listFactions,
  putClock,
  putFaction,
  queryKeys,
  type Clock,
  type Faction,
} from "../api";
import { usePrompt } from "../components/dialogs";
import { usePages } from "../components/Pager";
import { useT } from "../i18n";
import { CheckField, Failed, NumberField, RecordForm, RowActions, SelectField, TextField, slug } from "./worldFields";

/**
 * The campaign's factions and their clocks, for the organisers (plan 6 Task 12): every field, the DM-only ones
 * marked. What the characters know of a faction is whether it is `known`, and its standing word.
 */
export default function Factions({ campaignId }: { campaignId: string }) {
  const t = useT();
  const prompt = usePrompt();
  const client = useQueryClient();
  const factionsKey = queryKeys.campaignWorld(campaignId, "factions");
  const clocksKey = queryKeys.campaignWorld(campaignId, "clocks");
  const factions = useQuery({ queryKey: factionsKey, queryFn: () => listFactions(campaignId) });
  const clocks = useQuery({ queryKey: clocksKey, queryFn: () => listClocks(campaignId) });
  const [editing, setEditing] = useState<Faction | null>(null);
  const [editingClock, setEditingClock] = useState<Clock | null>(null);
  const done = () => {
    client.invalidateQueries({ queryKey: factionsKey });
    client.invalidateQueries({ queryKey: clocksKey });
  };
  const change = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: done });
  const busy = change.isPending;
  const save = (run: () => Promise<unknown>, close: () => void) => change.mutate(run, { onSuccess: close });
  const name = (id: string | null) => factions.data?.find((f) => f.id === id)?.name ?? id ?? "";
  const factionPages = usePages(factions.data ?? [], 20, t("pager.labelled", { name: t("world.factions") }));
  const clockPages = usePages(clocks.data ?? [], 20, t("pager.labelled", { name: t("world.clocks") }));

  async function addFaction() {
    const named = (await prompt({ title: t("world.addFaction"), label: t("world.name"), confirm: t("world.add") }))?.trim();
    if (named && slug(named)) change.mutate(() => putFaction(campaignId, slug(named), { name: named }));
  }
  async function addAClock() {
    const label = (await prompt({ title: t("world.addClock"), label: t("world.label"), confirm: t("world.add") }))?.trim();
    if (label) change.mutate(() => addClock(campaignId, { label, kind: "progress", segments: 4 }));
  }

  return (
    <div className="world-tables">
      <Failed error={change.error ?? factions.error ?? clocks.error} />
      <h3 id="world-factions">{t("world.factions")}</h3>
      {factions.data && factions.data.length === 0 && <p className="placeholder">{t("world.noFactions")}</p>}
      {factions.data && factions.data.length > 0 && (
        <>
          <table className="sheet-table world-table" aria-labelledby="world-factions">
            <thead>
              <tr>
                <th>{t("world.name")}</th>
                <th>{t("world.known")}</th>
                <th>{t("world.standing")}</th>
                <th>
                  {t("world.reputation")} <span className="dm-only-mark">{t("sheet.forTheDm")}</span>
                </th>
                <th>
                  {t("world.strength")} <span className="dm-only-mark">{t("sheet.forTheDm")}</span>
                </th>
                <th />
              </tr>
            </thead>
            <tbody>
              {factionPages.shown.map((faction) => (
                <Fragment key={faction.id}>
                  <tr>
                    <td>{faction.name}</td>
                    <td>{faction.known ? t("world.isKnown") : t("world.notKnown")}</td>
                    <td>{faction.standing}</td>
                    <td className="num">{faction.reputation}</td>
                    <td className="num">{faction.strength}</td>
                    <td>
                      <RowActions
                        name={faction.name}
                        busy={busy}
                        onEdit={() => setEditing(faction)}
                        onDelete={() => change.mutate(() => deleteFaction(campaignId, faction.id))}
                      />
                    </td>
                  </tr>
                  {editing?.id === faction.id && (
                    <tr>
                      <td colSpan={6}>
                        <FactionForm
                          faction={editing}
                          busy={busy}
                          onChange={setEditing}
                          onCancel={() => setEditing(null)}
                          onSave={() => {
                            const { id, standing: _standing, ...fields } = editing;
                            save(() => putFaction(campaignId, id, fields), () => setEditing(null));
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {factionPages.pager}
        </>
      )}
      <button type="button" disabled={busy} onClick={() => void addFaction()}>
        {t("world.addFaction")}
      </button>

      <h3 id="world-clocks">{t("world.clocks")}</h3>
      <p className="hint">
        {t("world.clocksIntro")} <span className="dm-only-mark">{t("sheet.forTheDm")}</span>
      </p>
      {clocks.data && clocks.data.length === 0 && <p className="placeholder">{t("world.noClocks")}</p>}
      {clocks.data && clocks.data.length > 0 && (
        <>
          <table className="sheet-table world-table" aria-labelledby="world-clocks">
            <thead>
              <tr>
                <th>{t("world.label")}</th>
                <th>{t("world.faction")}</th>
                <th>{t("world.progress")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {clockPages.shown.map((clock) => (
                <Fragment key={clock.id}>
                  <tr>
                    <td>{clock.label}</td>
                    <td>{name(clock.faction)}</td>
                    <td>
                      {clock.done_day !== null
                        ? t("world.clockDone", { day: String(clock.done_day) })
                        : clock.kind === "countdown"
                          ? t("world.daysLeft", { count: String(clock.days_remaining ?? 0) })
                          : t("world.segments", { filled: String(clock.filled ?? 0), segments: String(clock.segments ?? 0) })}
                    </td>
                    <td>
                      <RowActions
                        name={clock.label}
                        busy={busy}
                        onEdit={() => setEditingClock(clock)}
                        onDelete={() => change.mutate(() => deleteClock(campaignId, clock.id))}
                      />
                    </td>
                  </tr>
                  {editingClock?.id === clock.id && (
                    <tr>
                      <td colSpan={4}>
                        <ClockForm
                          clock={editingClock}
                          factions={factions.data ?? []}
                          busy={busy}
                          onChange={setEditingClock}
                          onCancel={() => setEditingClock(null)}
                          onSave={() => {
                            const c = editingClock;
                            const body = {
                              label: c.label,
                              kind: c.kind,
                              faction: c.faction ?? "",
                              on_complete: c.on_complete,
                              ...(c.kind === "countdown"
                                ? { days_remaining: c.days_remaining ?? 0 }
                                : { segments: c.segments ?? 1, filled: c.filled ?? 0 }),
                            };
                            save(() => putClock(campaignId, c.id, body), () => setEditingClock(null));
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {clockPages.pager}
        </>
      )}
      <button type="button" disabled={busy} onClick={() => void addAClock()}>
        {t("world.addClock")}
      </button>
    </div>
  );
}

function FactionForm({
  faction,
  busy,
  onChange,
  onSave,
  onCancel,
}: {
  faction: Faction;
  busy: boolean;
  onChange: (faction: Faction) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const set = (patch: Partial<Faction>) => onChange({ ...faction, ...patch });
  return (
    <RecordForm busy={busy} onSave={onSave} onCancel={onCancel}>
      <TextField label={t("world.name")} value={faction.name} onChange={(name) => set({ name })} />
      <CheckField label={t("world.knownToThem")} checked={faction.known} onChange={(known) => set({ known })} />
      <TextField label={t("world.alignment")} value={faction.alignment} onChange={(alignment) => set({ alignment })} dmOnly />
      <TextField label={t("world.goals")} value={faction.goals} onChange={(goals) => set({ goals })} dmOnly />
      <TextField label={t("world.scope")} value={faction.scope} onChange={(scope) => set({ scope })} dmOnly />
      <NumberField
        label={t("world.reputation")}
        value={faction.reputation}
        min={-100}
        max={100}
        onChange={(reputation) => set({ reputation: reputation ?? 0 })}
        dmOnly
      />
      <NumberField
        label={t("world.strength")}
        value={faction.strength}
        min={0}
        max={100}
        onChange={(strength) => set({ strength: strength ?? 0 })}
        dmOnly
      />
      <TextField label={t("world.dmNotes")} value={faction.notes_md} onChange={(notes_md) => set({ notes_md })} multiline dmOnly />
    </RecordForm>
  );
}

function ClockForm({
  clock,
  factions,
  busy,
  onChange,
  onSave,
  onCancel,
}: {
  clock: Clock;
  factions: Faction[];
  busy: boolean;
  onChange: (clock: Clock) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const set = (patch: Partial<Clock>) => onChange({ ...clock, ...patch });
  return (
    <RecordForm busy={busy} onSave={onSave} onCancel={onCancel}>
      <TextField label={t("world.label")} value={clock.label} onChange={(label) => set({ label })} />
      <SelectField
        label={t("world.clockKind")}
        value={clock.kind}
        options={CLOCK_KINDS.map((kind) => ({ value: kind, label: t(`world.clockKind.${kind}`) }))}
        onChange={(kind) => set({ kind: kind as Clock["kind"] })}
      />
      <SelectField
        label={t("world.faction")}
        value={clock.faction ?? ""}
        options={[{ value: "", label: t("world.noFaction") }, ...factions.map((f) => ({ value: f.id, label: f.name }))]}
        onChange={(faction) => set({ faction: faction || null })}
      />
      {clock.kind === "countdown" ? (
        <NumberField label={t("world.daysLeftField")} value={clock.days_remaining} min={0} onChange={(d) => set({ days_remaining: d })} />
      ) : (
        <>
          <NumberField label={t("world.segmentsField")} value={clock.segments} min={1} onChange={(s) => set({ segments: s })} />
          <NumberField label={t("world.filled")} value={clock.filled} min={0} onChange={(f) => set({ filled: f })} />
        </>
      )}
      <TextField label={t("world.onComplete")} value={clock.on_complete} onChange={(on_complete) => set({ on_complete })} multiline />
    </RecordForm>
  );
}
