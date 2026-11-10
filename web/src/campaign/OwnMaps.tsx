import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createOwnMap, deleteOwnMap, listOwnMaps, queryKeys } from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { Failed } from "./worldFields";

export const ownMapPath = (campaignId: string, name: string) =>
  `/campaigns/${encodeURIComponent(campaignId)}/own-maps/${encodeURIComponent(name)}`;

/**
 * The campaign's own maps (campaign maps, 2026-10-23), for the organisers: dungeon maps made for this campaign, such as
 * a district the table invented, played beside the module's but never part of it or its export. Each opens the map
 * editor; a new one is made empty and opened there.
 */
export default function OwnMaps({ campaignId }: { campaignId: string }) {
  const t = useT();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [name, setName] = useState("");
  const maps = useQuery({ queryKey: queryKeys.ownMaps(campaignId), queryFn: () => listOwnMaps(campaignId) });
  const refresh = () => {
    client.invalidateQueries({ queryKey: queryKeys.ownMaps(campaignId) });
    client.invalidateQueries({ queryKey: queryKeys.campaign(campaignId), exact: true });
  };
  const create = useMutation({
    mutationFn: (wanted: string) => createOwnMap(campaignId, wanted),
    onSuccess: (made) => {
      refresh();
      navigate(ownMapPath(campaignId, made.name));
    },
  });
  const remove = useMutation({ mutationFn: (gone: string) => deleteOwnMap(campaignId, gone), onSuccess: refresh });
  const listed = maps.data ?? [];

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) create.mutate(name.trim());
  };

  return (
    <div className="own-maps">
      <p className="lede">{t("ownMaps.intro")}</p>
      <Failed error={create.error ?? remove.error ?? maps.error} />
      {listed.length === 0 && maps.isSuccess && <p className="placeholder">{t("ownMaps.none")}</p>}
      {listed.length > 0 && (
        <ul className="rows">
          {listed.map((map) => (
            <li key={map.name} className="row">
              <Link to={ownMapPath(campaignId, map.name)} className="row-title">
                {map.name}
              </Link>
              <span className="tag">{t("ownMaps.tag")}</span>
              <div className="actions">
                <button
                  type="button"
                  className="danger"
                  disabled={remove.isPending}
                  onClick={async () =>
                    (await confirm({
                      title: t("ownMaps.deleteConfirm", { name: map.name }),
                      confirm: t("dialog.delete"),
                      danger: true,
                    })) && remove.mutate(map.name)
                  }
                >
                  {t("dialog.delete")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <form className="inline-form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="own-map-name">{t("ownMaps.newName")}</label>
          <input id="own-map-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <button type="submit" disabled={create.isPending || !name.trim()}>
          {t("ownMaps.make")}
        </button>
      </form>
    </div>
  );
}
