import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { QUEST_SCOPES, QUEST_STATUSES, deleteQuest, listQuests, putQuest, queryKeys, type Quest } from "../api";
import { usePrompt } from "../components/dialogs";
import { usePages } from "../components/Pager";
import { useT } from "../i18n";
import { CheckField, Failed, RecordForm, RowActions, SelectField, TextField, slug } from "./worldFields";

/**
 * The campaign's quests, for the organisers (plan 6 Task 12). The characters see a quest only once it is known,
 * with only the notes marked known; the DM's notes never.
 */
export default function Quests({ campaignId }: { campaignId: string }) {
  const t = useT();
  const prompt = usePrompt();
  const client = useQueryClient();
  const key = queryKeys.campaignWorld(campaignId, "quests");
  const quests = useQuery({ queryKey: key, queryFn: () => listQuests(campaignId) });
  const [editing, setEditing] = useState<Quest | null>(null);
  const pages = usePages(quests.data ?? [], 20, t("pager.labelled", { name: t("world.quests") }));
  const change = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: () => client.invalidateQueries({ queryKey: key }),
  });
  const busy = change.isPending;

  async function add() {
    const title = (await prompt({ title: t("world.addQuest"), label: t("world.title"), confirm: t("world.add") }))?.trim();
    if (title && slug(title)) change.mutate(() => putQuest(campaignId, slug(title), { title }));
  }

  return (
    <div className="world-tables">
      <Failed error={change.error ?? quests.error} />
      <h3 id="world-quests">{t("world.quests")}</h3>
      {quests.data && quests.data.length === 0 && <p className="placeholder">{t("world.noQuests")}</p>}
      {quests.data && quests.data.length > 0 && (
        <>
          <table className="sheet-table world-table" aria-labelledby="world-quests">
            <thead>
              <tr>
                <th>{t("world.title")}</th>
                <th>{t("world.status")}</th>
                <th>{t("world.known")}</th>
                <th>{t("world.giver")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pages.shown.map((quest) => (
                <Fragment key={quest.id}>
                  <tr>
                    <td>{quest.title}</td>
                    <td>{t(`quest.status.${quest.status}`)}</td>
                    <td>{quest.known ? t("world.isKnown") : t("world.notKnown")}</td>
                    <td>{quest.giver}</td>
                    <td>
                      <RowActions
                        name={quest.title}
                        busy={busy}
                        onEdit={() => setEditing(quest)}
                        onDelete={() => change.mutate(() => deleteQuest(campaignId, quest.id))}
                      />
                    </td>
                  </tr>
                  {editing?.id === quest.id && (
                    <tr>
                      <td colSpan={5}>
                        <QuestForm
                          quest={editing}
                          busy={busy}
                          onChange={setEditing}
                          onCancel={() => setEditing(null)}
                          onSave={() => {
                            const { title, giver, scope, stakes, status, known, related, log, notes_md } = editing;
                            const body = { title, giver, scope, stakes, status, known, related, log, notes_md };
                            change.mutate(() => putQuest(campaignId, editing.id, body), { onSuccess: () => setEditing(null) });
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
        {t("world.addQuest")}
      </button>
    </div>
  );
}

function QuestForm({
  quest,
  busy,
  onChange,
  onSave,
  onCancel,
}: {
  quest: Quest;
  busy: boolean;
  onChange: (quest: Quest) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const set = (patch: Partial<Quest>) => onChange({ ...quest, ...patch });
  const setNote = (index: number, patch: Partial<Quest["log"][number]>) =>
    set({ log: quest.log.map((note, i) => (i === index ? { ...note, ...patch } : note)) });
  return (
    <RecordForm busy={busy} onSave={onSave} onCancel={onCancel}>
      <TextField label={t("world.title")} value={quest.title} onChange={(title) => set({ title })} />
      <SelectField
        label={t("world.status")}
        value={quest.status}
        options={QUEST_STATUSES.map((s) => ({ value: s, label: t(`quest.status.${s}`) }))}
        onChange={(status) => set({ status })}
      />
      <CheckField label={t("world.knownToThem")} checked={quest.known} onChange={(known) => set({ known })} />
      <TextField label={t("world.giver")} value={quest.giver} onChange={(giver) => set({ giver })} />
      <SelectField
        label={t("world.scope")}
        value={quest.scope}
        options={QUEST_SCOPES.map((s) => ({ value: s, label: t(`quest.scope.${s}`) }))}
        onChange={(scope) => set({ scope })}
      />
      <TextField label={t("world.stakes")} value={quest.stakes} onChange={(stakes) => set({ stakes })} multiline />
      <fieldset className="quest-notes">
        <legend>{t("world.questNotes")}</legend>
        {quest.log.map((note, index) => (
          <div key={index} className="quest-note">
            <TextField
              label={t("world.noteN", { n: String(index + 1), day: String(note.day) })}
              value={note.text}
              onChange={(text) => setNote(index, { text })}
            />
            <CheckField
              label={t("world.noteKnown", { n: String(index + 1) })}
              checked={note.known}
              onChange={(known) => setNote(index, { known })}
            />
          </div>
        ))}
      </fieldset>
      <TextField label={t("world.dmNotes")} value={quest.notes_md} onChange={(notes_md) => set({ notes_md })} multiline dmOnly />
    </RecordForm>
  );
}
