import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { getWorlds, queryKeys } from "../api";
import { WorldMapList } from "../campaign/WorldMaps";
import { Failed } from "../campaign/worldFields";
import { useT } from "../i18n";
import { exportUrl, ownerPage, type WorldMapOwner } from "../worldmap/editorApi";
import { copyToSetting, listWorldMaps, worldMapsKey, type WorldMapRow } from "../worldmap/importApi";

/** The setting a module names in its details, by id or title, else the first. */
function settingOf(settings: { id: string; title: string }[], named: string | undefined): string {
  const wanted = named?.trim().toLowerCase();
  return settings.find((s) => s.id.toLowerCase() === wanted || s.title.toLowerCase() === wanted)?.id ?? settings[0]?.id ?? "";
}

/**
 * A module's world maps, for the organisers: as a campaign's (Import, Edit, Review, the picture, Delete), with Export,
 * and for a ready one "Copy to <setting>'s maps", which makes it the setting's own map on this install; once the
 * setting has a map of that name, "In <setting>'s maps" links to the setting's Maps tab.
 */
export default function WorldMapsPanel({ moduleId, setting }: { moduleId: string; setting?: string }) {
  const t = useT();
  const id = useId();
  const client = useQueryClient();
  const owner: WorldMapOwner = { kind: "module", moduleId };
  const worlds = useQuery({ queryKey: queryKeys.worlds, queryFn: getWorlds });
  const settings = worlds.data?.settings ?? [];
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = settings.some((s) => s.id === picked) ? picked! : settingOf(settings, setting);
  const settingOwner: WorldMapOwner = { kind: "setting", settingId: chosen };
  const settingMaps = useQuery({
    queryKey: worldMapsKey(settingOwner),
    queryFn: () => listWorldMaps(settingOwner),
    enabled: chosen !== "",
  });
  const title = settings.find((s) => s.id === chosen)?.title ?? chosen;

  const copy = useMutation({
    mutationFn: (name: string) => copyToSetting(chosen, { module_id: moduleId, name }),
    onSuccess: () => client.invalidateQueries({ queryKey: worldMapsKey(settingOwner) }),
  });
  const copied = (map: WorldMapRow) => settingMaps.data?.some((m) => m.name === map.name) ?? false;

  return (
    <section className="world-maps-panel">
      <h2>{t("worldMaps.moduleTitle")}</h2>
      <Failed error={copy.error} />
      {settings.length > 1 && (
        <div className="field">
          <label htmlFor={`${id}-setting`}>{t("worldMaps.setting")}</label>
          <select id={`${id}-setting`} value={chosen} onChange={(e) => setPicked(e.target.value)}>
            {settings.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
        </div>
      )}
      <WorldMapList
        owner={owner}
        empty={t("worldMaps.moduleNone")}
        actions={(map) => (
          <>
            <a className="button-like" href={exportUrl(owner, map.name)} download>
              {t("worldMaps.export")}
            </a>
            {chosen && copied(map) && (
              <Link className="tag" to={ownerPage(settingOwner)}>
                {t("worldMaps.usedFor", { setting: title })}
              </Link>
            )}
            {map.status === "ready" && chosen && settingMaps.isSuccess && !copied(map) && (
              <button type="button" disabled={copy.isPending} onClick={() => copy.mutate(map.name)}>
                {t("worldMaps.useFor", { setting: title })}
              </button>
            )}
          </>
        )}
      />
    </section>
  );
}
