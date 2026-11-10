import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import {
  POSSESSION_KINDS,
  addPossession,
  deletePossession,
  listPossessions,
  putPossession,
  queryKeys,
  type Possession,
} from "../api";
import Portrait from "../components/Portrait";
import { usePrompt } from "../components/dialogs";
import { usePages } from "../components/Pager";
import { useT } from "../i18n";
import { Failed, NumberField, RecordForm, RowActions, SelectField, TextField } from "./worldFields";

/**
 * The campaign's possessions, for the organisers (plan 6 Task 12): the party's and each character's mounts,
 * vehicles, ships and houses. The players see them all, but never the DM's notes.
 */
export default function Possessions({
  campaignId,
  owners = [],
}: {
  campaignId: string;
  /** The PCs a possession can belong to, besides the party. */
  owners?: { id: string; name: string }[];
}) {
  const t = useT();
  const prompt = usePrompt();
  const client = useQueryClient();
  const key = queryKeys.campaignWorld(campaignId, "possessions");
  const possessions = useQuery({ queryKey: key, queryFn: () => listPossessions(campaignId) });
  const [editing, setEditing] = useState<Possession | null>(null);
  const pages = usePages(possessions.data ?? [], 20, t("pager.labelled", { name: t("world.possessions") }));
  const change = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  const busy = change.isPending;

  async function add() {
    const name = (await prompt({ title: t("world.addPossession"), label: t("world.name"), confirm: t("world.add") }))?.trim();
    if (name) change.mutate(() => addPossession(campaignId, { name, kind: "other" }));
  }

  return (
    <div className="world-tables">
      <Failed error={change.error ?? possessions.error} />
      <h3 id="world-possessions">{t("world.possessions")}</h3>
      {possessions.data && possessions.data.length === 0 && <p className="placeholder">{t("world.noPossessions")}</p>}
      {possessions.data && possessions.data.length > 0 && (
        <>
          <table className="sheet-table world-table" aria-labelledby="world-possessions">
            <thead>
              <tr>
                <th>{t("world.name")}</th>
                <th>{t("world.kind")}</th>
                <th>{t("world.owner")}</th>
                <th>{t("world.location")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pages.shown.map((p) => (
                <Fragment key={p.id}>
                  <tr>
                    <td className="possession-name">
                      <Portrait campaignId={campaignId} portrait={p.portrait} name={p.name} size={28} />
                      <span>{p.name}</span>
                    </td>
                    <td>{t(`possession.kind.${p.kind}`)}</td>
                    <td>{p.owner ?? t("world.theParty")}</td>
                    <td>{p.location}</td>
                    <td>
                      <RowActions
                        name={p.name}
                        busy={busy}
                        onEdit={() => setEditing(p)}
                        onDelete={() => change.mutate(() => deletePossession(campaignId, p.id))}
                      />
                    </td>
                  </tr>
                  {editing?.id === p.id && (
                    <tr>
                      <td colSpan={5}>
                        <PossessionForm
                          possession={editing}
                          owners={owners}
                          busy={busy}
                          onChange={setEditing}
                          onCancel={() => setEditing(null)}
                          onSave={() => {
                            const e = editing;
                            const body = {
                              name: e.name,
                              kind: e.kind,
                              owner: e.owner_id ?? "",
                              location: e.location,
                              value_gp: e.value_gp,
                              description: e.description,
                              notes_md: e.notes_md,
                            };
                            change.mutate(() => putPossession(campaignId, e.id, body), { onSuccess: () => setEditing(null) });
                          }}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {pages.pager}
        </>
      )}
      <button type="button" disabled={busy} onClick={() => void add()}>
        {t("world.addPossession")}
      </button>
    </div>
  );
}

function PossessionForm({
  possession,
  owners,
  busy,
  onChange,
  onSave,
  onCancel,
}: {
  possession: Possession;
  owners: { id: string; name: string }[];
  busy: boolean;
  onChange: (possession: Possession) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const set = (patch: Partial<Possession>) => onChange({ ...possession, ...patch });
  return (
    <RecordForm busy={busy} onSave={onSave} onCancel={onCancel}>
      <TextField label={t("world.name")} value={possession.name} onChange={(name) => set({ name })} />
      <SelectField
        label={t("world.kind")}
        value={possession.kind}
        options={POSSESSION_KINDS.map((k) => ({ value: k, label: t(`possession.kind.${k}`) }))}
        onChange={(kind) => set({ kind })}
      />
      <SelectField
        label={t("world.owner")}
        value={possession.owner_id ?? ""}
        options={[{ value: "", label: t("world.theParty") }, ...owners.map((o) => ({ value: o.id, label: o.name }))]}
        onChange={(owner) => set({ owner_id: owner || null })}
      />
      <TextField label={t("world.location")} value={possession.location} onChange={(location) => set({ location })} />
      <NumberField label={t("world.value")} value={possession.value_gp} min={0} onChange={(v) => set({ value_gp: v ?? 0 })} />
      <TextField
        label={t("world.description")}
        value={possession.description}
        onChange={(description) => set({ description })}
        multiline
      />
      <TextField
        label={t("world.dmNotes")}
        value={possession.notes_md}
        onChange={(notes_md) => set({ notes_md })}
        multiline
        dmOnly
      />
    </RecordForm>
  );
}
