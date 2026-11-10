import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { listCampaigns, queryKeys } from "../api";
import { useT } from "../i18n";
import {
  addMember,
  boardKeys,
  createZone,
  deleteZone,
  getZonePeople,
  removeMember,
  setModerators,
  updateZone,
  type Level,
  type Zone,
} from "./api";
import { sayError } from "./show";

// A zone's settings and its people (DEL-297). The server enforces who may do what; these dialogs only keep from
// offering what it refuses: without `wide` (not an organiser) read and write are `table` or `members` and the
// campaign is the table's own; write is never wider than read; `table` needs a campaign. A wider level an organiser set
// shows to a host as it is, offered but not to be chosen again: Save sends it back unchanged, which the server takes.

const LEVELS: Level[] = ["everybody", "accounts", "members", "table"];

/** The levels write may take for a read level: its own and narrower ones; `table` and `members` are only themselves. */
function writeLevels(read: Level, wide: boolean, hasCampaign: boolean): Level[] {
  const levels: Level[] = read === "everybody" || read === "accounts" ? ["accounts", "members", "table"] : [read];
  return levels.filter((level) => (wide || level === "members" || level === "table") && (level !== "table" || hasCampaign));
}

/** The levels read may take. */
function readLevels(wide: boolean, hasCampaign: boolean): Level[] {
  return LEVELS.filter((level) => (wide || level === "members" || level === "table") && (level !== "table" || hasCampaign));
}

/** The usernames in a comma- or space-separated field. */
const usernames = (text: string) => text.split(/[\s,]+/).filter(Boolean);

/**
 * Makes a zone, or changes `zone`. `campaignId` is the table's own, for a host's zone; an organiser (`wide`) picks the
 * campaign from those they see. `topics` is how many topics Remove zone will take with it.
 */
export default function ZoneSettings({
  zone,
  campaignId,
  wide,
  topics = 0,
  onDone,
  onRemoved,
}: {
  zone?: Zone;
  campaignId?: string;
  wide: boolean;
  topics?: number;
  onDone: () => void;
  /** Called, instead of `onDone`, once the zone is removed: the page that showed it has nothing left to show. */
  onRemoved?: () => void;
}) {
  const t = useT();
  const client = useQueryClient();
  const [name, setName] = useState(zone?.name ?? "");
  const [description, setDescription] = useState(zone?.description ?? "");
  const [campaign, setCampaign] = useState<string | null>(zone ? zone.campaign_id : (campaignId ?? null));
  const [read, setRead] = useState<Level>(zone?.read ?? (campaign ? "table" : wide ? "accounts" : "members"));
  const [write, setWrite] = useState<Level>(zone?.write ?? (campaign ? "table" : wide ? "accounts" : "members"));
  const [pictures, setPictures] = useState(zone?.pictures ?? false);
  const [moderators, setModeratorText] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  // The zone a first Save made: when its moderators then fail, Save again changes that zone, not makes another.
  const [made, setMade] = useState<Zone | null>(null);
  const existing = zone ?? made ?? undefined;

  const campaigns = useQuery({ queryKey: queryKeys.campaigns, queryFn: listCampaigns, enabled: wide });
  const people = useQuery({ queryKey: boardKeys.people(zone?.id ?? ""), queryFn: () => getZonePeople(zone!.id), enabled: !!zone });
  const moderatorText = moderators ?? (people.data?.moderators.map((p) => p.username).join(", ") ?? "");

  const hasCampaign = campaign !== null;
  const reads = readLevels(wide, hasCampaign);
  const writes = writeLevels(read, wide, hasCampaign);
  // Whatever is chosen stays a pair the server takes: when the campaign or the read level changes, so may write.
  const changeCampaign = (id: string | null) => {
    setCampaign(id);
    if (id !== null) return;
    const nextRead: Level = read === "table" ? (wide ? "accounts" : "members") : read;
    const allowed = writeLevels(nextRead, wide, false);
    setRead(nextRead);
    if (!allowed.includes(write)) setWrite(allowed[0]);
  };
  const changeRead = (level: Level) => {
    setRead(level);
    if (!writeLevels(level, wide, hasCampaign).includes(write)) setWrite(writeLevels(level, wide, hasCampaign)[0]);
  };

  const refresh = () => client.invalidateQueries({ queryKey: boardKeys.all });
  const save = useMutation({
    mutationFn: async () => {
      const fields = { name: name.trim(), description: description.trim(), read, write, pictures };
      const saved = existing
        ? await updateZone(existing.id, wide ? { ...fields, campaign_id: campaign } : fields)
        : await createZone(wide || campaign ? { ...fields, campaign_id: campaign } : fields);
      if (!existing) setMade(saved.zone);
      const wanted = usernames(moderatorText);
      const same = people.data?.moderators.map((p) => p.username).join(",") === wanted.join(",");
      if (existing ? !same && (people.data || !zone) : wanted.length > 0) await setModerators(saved.zone.id, wanted);
    },
    onSuccess: async () => {
      await refresh();
      onDone();
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteZone(zone!.id),
    onSuccess: async () => {
      await refresh();
      (onRemoved ?? onDone)();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) save.mutate();
  }

  const error = save.error ?? remove.error;
  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onDone()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog board-dialog" aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{zone ? t("board.zoneSettings") : t("board.newZone")}</Dialog.Title>
          <form onSubmit={submit}>
            <label className="board-field">
              <span>{t("board.zoneName")}</span>
              <input value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="board-field">
              <span>{t("board.zoneDescription")}</span>
              <textarea value={description} rows={2} maxLength={500} onChange={(e) => setDescription(e.target.value)} />
            </label>
            {wide && (
              <label className="board-field">
                <span>{t("board.zoneCampaign")}</span>
                <select value={campaign ?? ""} onChange={(e) => changeCampaign(e.target.value || null)}>
                  <option value="">{t("board.noCampaign")}</option>
                  {(campaigns.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                  {campaign && !(campaigns.data ?? []).some((c) => c.id === campaign) && <option value={campaign}>{campaign}</option>}
                </select>
              </label>
            )}
            <label className="board-field">
              <span>{t("board.zoneRead")}</span>
              <select value={read} onChange={(e) => changeRead(e.target.value as Level)}>
                {reads.map((level) => (
                  <option key={level} value={level}>
                    {t(`board.level.${level}`)}
                  </option>
                ))}
                {!reads.includes(read) && (
                  <option value={read} disabled>
                    {t(`board.level.${read}`)}
                  </option>
                )}
              </select>
            </label>
            <label className="board-field">
              <span>{t("board.zoneWrite")}</span>
              <select value={write} onChange={(e) => setWrite(e.target.value as Level)}>
                {writes.map((level) => (
                  <option key={level} value={level}>
                    {t(`board.level.${level}`)}
                  </option>
                ))}
                {!writes.includes(write) && (
                  <option value={write} disabled>
                    {t(`board.level.${write}`)}
                  </option>
                )}
              </select>
            </label>
            <label className="board-check">
              <input type="checkbox" checked={pictures} onChange={(e) => setPictures(e.target.checked)} />
              {t("board.zonePictures")}
            </label>
            <label className="board-field">
              <span>{t("board.zoneModerators")}</span>
              <input value={moderatorText} placeholder={t("board.usernames")} onChange={(e) => setModeratorText(e.target.value)} />
            </label>
            {removing && zone && (
              <div className="notice error" role="alert">
                <p>{t("board.removeZoneConfirm", { name: zone.name, count: String(topics) })}</p>
                <button type="button" className="danger" disabled={remove.isPending} onClick={() => remove.mutate()}>
                  {t("board.removeZoneYes")}
                </button>
              </div>
            )}
            {error && (
              <p className="notice error" role="alert">
                {sayError(error)}
              </p>
            )}
            <div className="dialog-actions">
              {zone && zone.rights.manage_wide && !removing && (
                <button type="button" className="danger" onClick={() => setRemoving(true)}>
                  {t("board.removeZone")}
                </button>
              )}
              <Dialog.Close asChild>
                <button type="button">{t("board.cancel")}</button>
              </Dialog.Close>
              <button type="submit" className="primary" disabled={save.isPending || !name.trim()}>
                {t("board.save")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A members zone's people: who is in it, adding by username, and removing each. */
export function ZonePeople({ zone, onDone }: { zone: Zone; onDone: () => void }) {
  const t = useT();
  const client = useQueryClient();
  const [username, setUsername] = useState("");
  const people = useQuery({ queryKey: boardKeys.people(zone.id), queryFn: () => getZonePeople(zone.id) });
  const change = useMutation({
    mutationFn: (work: () => Promise<unknown>) => work(),
    onSuccess: () => client.invalidateQueries({ queryKey: boardKeys.people(zone.id) }),
  });

  function add(e: FormEvent) {
    e.preventDefault();
    const who = username.trim();
    if (!who) return;
    change.mutate(() => addMember(zone.id, who), { onSuccess: () => setUsername("") });
  }

  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onDone()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog board-dialog" aria-describedby={undefined}>
          <Dialog.Title className="dialog-title">{t("board.people")}</Dialog.Title>
          {people.isPending ? (
            <p className="board-quiet">{t("board.loading")}</p>
          ) : people.isError ? (
            <p className="notice error" role="alert">
              {sayError(people.error)}
            </p>
          ) : (
            <>
              <h3>{t("board.members")}</h3>
              {people.data.members.length === 0 && <p className="board-quiet">{t("board.noMembers")}</p>}
              <ul className="board-people">
                {people.data.members.map((person) => (
                  <li key={person.account_id}>
                    <span>
                      {person.display_name} <span className="board-meta">@{person.username}</span>
                    </span>
                    <button
                      type="button"
                      aria-label={t("board.removeMember", { name: person.display_name })}
                      disabled={change.isPending}
                      onClick={() => change.mutate(() => removeMember(zone.id, person.account_id))}
                    >
                      {t("board.remove")}
                    </button>
                  </li>
                ))}
              </ul>
              <form onSubmit={add}>
                <label className="board-field">
                  <span>{t("board.memberUsername")}</span>
                  <input value={username} onChange={(e) => setUsername(e.target.value)} />
                </label>
                <button type="submit" disabled={change.isPending || !username.trim()}>
                  {t("board.addMember")}
                </button>
              </form>
            </>
          )}
          {change.error && (
            <p className="notice error" role="alert">
              {sayError(change.error)}
            </p>
          )}
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button type="button">{t("board.done")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
