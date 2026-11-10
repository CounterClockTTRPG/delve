import { useQuery } from "@tanstack/react-query";
import { WorldMapList } from "../campaign/WorldMaps";
import { useT } from "../i18n";
import type { WorldMapOwner } from "../worldmap/editorApi";
import { listWorldMaps, worldMapsKey } from "../worldmap/importApi";
import { getSetting, settingKeys } from "./api";

/**
 * A setting's world maps on this install, for the organisers: each opens the editor, or its review while it is in
 * review, and Import reads one from GeoJSON or a picture. While the install has no ready map of its own, a line names
 * the built-in map that new campaigns copy instead.
 */
export default function MapsTab({ settingId }: { settingId: string }) {
  const t = useT();
  const owner: WorldMapOwner = { kind: "setting", settingId };
  // The setting's page has read it already: this is its cache.
  const setting = useQuery({ queryKey: settingKeys.one(settingId), queryFn: () => getSetting(settingId) });
  // The same query as the list's, so this reads no more than the list does.
  const maps = useQuery({ queryKey: worldMapsKey(owner), queryFn: () => listWorldMaps(owner) });
  const builtIn = setting.data?.built_in_maps.map((m) => m.title || m.name).join(", ");

  return (
    <>
      {setting.data?.maps_in_use === "built-in" && builtIn && <p>{t("setting.maps.builtIn", { maps: builtIn })}</p>}
      {maps.data?.some((m) => m.status === "review") && <p className="row-meta">{t("setting.maps.review")}</p>}
      <WorldMapList owner={owner} empty={t("setting.maps.empty")} />
    </>
  );
}
