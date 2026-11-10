import "./leafletGlobal";
import "@geoman-io/leaflet-geoman-free";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import L from "leaflet";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { NeedsToken } from "../api";
import { useLanguage, useT } from "../i18n";
import { pictureTileUrl } from "./api";
import { fromLatLng, type Point } from "./crs";
import { getWorldMap, worldMapKey, type WorldMapOwner } from "./editorApi";
import { setKnowledge, type StartHow } from "./importApi";
import { reviewView } from "./ReviewPage";
import { useLeafletMap } from "./useLeaflet";
import WorldMapView from "./WorldMapView";
import styles from "./WorldImport.module.css";

const HOWS: StartHow[] = ["everything", "nothing", "regions", "area"];

/** Geoman's polygon tool on the nearest `WorldMapView`: one area at a time, its ring in km given to `onRing`. */
function DrawArea({ onRing }: { onRing: (ring: Point[]) => void }) {
  const map = useLeafletMap();
  const t = useT();
  const language = useLanguage();
  const latest = useRef(onRing);
  latest.current = onRing;
  useEffect(() => {
    if (!map) return;
    map.pm.setLang(
      language === "nl" ? "nl" : "en",
      {
        tooltips: {
          firstVertex: t("worldMapEditor.draw.firstVertex"),
          continueLine: t("worldMapEditor.draw.continueLine"),
          finishPoly: t("worldMapEditor.draw.finishPoly"),
        },
      },
      "en",
    );
    let drawn: L.Layer | null = null;
    const draw = () => map.pm.enableDraw("Polygon", { continueDrawing: false });
    const onCreate = (e: { layer: L.Layer }) => {
      drawn?.remove();
      drawn = e.layer;
      const latLngs = (e.layer as L.Polygon).getLatLngs() as L.LatLng[][];
      latest.current((latLngs[0] ?? []).map(fromLatLng));
      draw();
    };
    map.on("pm:create", onCreate);
    // Geoman draws once the map has its view, which the map view sets after its children's effects.
    let gone = false;
    map.whenReady(() => gone || draw());
    return () => {
      gone = true;
      map.off("pm:create", onCreate);
      map.pm.disableDraw();
      drawn?.remove();
    };
  }, [map, language, t]);
  return null;
}

/**
 * "What the party knows at the start" of a campaign's world map: everything, nothing, some of its regions (with
 * their roads, clipped), or an area drawn on the map. Setting it replaces what the party knows of that map.
 */
export default function StartKnowledge({ campaignId, name, title }: { campaignId: string; name: string; title: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button">{t("worldStart.open")}</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={`dialog ${styles.dialog}`}>
          <Dialog.Title className="dialog-title">{t("worldStart.title", { title: title || name })}</Dialog.Title>
          <Dialog.Description className="dialog-body">{t("worldStart.lede")}</Dialog.Description>
          <StartForm campaignId={campaignId} name={name} onSet={() => setOpen(false)} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function StartForm({ campaignId, name, onSet }: { campaignId: string; name: string; onSet: () => void }) {
  const t = useT();
  const id = useId();
  const client = useQueryClient();
  const owner: WorldMapOwner = { kind: "campaign", campaignId };
  const map = useQuery({ queryKey: worldMapKey(owner, name), queryFn: () => getWorldMap(owner, name) });
  const [how, setHow] = useState<StartHow>("nothing");
  const [regions, setRegions] = useState<string[]>([]);
  const [ring, setRing] = useState<Point[]>([]);
  const view = useMemo(() => (map.data ? reviewView(map.data) : null), [map.data]);
  const listed = map.data?.geo.features.filter((f) => f.properties.layer === "regions") ?? [];

  const set = useMutation({
    mutationFn: () =>
      setKnowledge(campaignId, name, {
        how,
        ...(how === "regions" ? { regions } : {}),
        ...(how === "area" ? { ring } : {}),
      }),
    onSuccess: () => {
      // The list, the map's own document and the play screen's world: a `world` event would do the same.
      client.invalidateQueries({ queryKey: ["campaign", campaignId, "world"] });
      client.invalidateQueries({ queryKey: worldMapKey(owner, name) });
      onSet();
    },
  });

  const ready = how === "regions" ? regions.length > 0 : how === "area" ? ring.length >= 3 : true;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) set.mutate();
      }}
    >
      <fieldset>
        <legend>{t("worldStart.how")}</legend>
        {HOWS.map((h) => (
          <label key={h} className="checkbox">
            <input type="radio" name={`${id}-how`} checked={how === h} onChange={() => setHow(h)} />
            {t(`worldStart.how.${h}`)}
          </label>
        ))}
      </fieldset>
      {how === "regions" &&
        (listed.length === 0 && map.isSuccess ? (
          <p className="placeholder">{t("worldStart.noRegions")}</p>
        ) : (
          <fieldset>
            <legend>{t("worldStart.regions")}</legend>
            {listed.map((f) => (
              <label key={f.id} className="checkbox">
                <input
                  type="checkbox"
                  checked={regions.includes(f.id)}
                  onChange={(e) =>
                    setRegions(e.target.checked ? [...regions, f.id] : regions.filter((r) => r !== f.id))
                  }
                />
                {f.properties.name || f.id}
              </label>
            ))}
          </fieldset>
        ))}
      {how === "area" && view && (
        <>
          <p className="row-meta">{t("worldStart.drawHint")}</p>
          <div className={styles.startMap}>
            <WorldMapView view={view} tileUrl={map.data?.picture ? pictureTileUrl(map.data.picture) : null}>
              <DrawArea onRing={setRing} />
            </WorldMapView>
          </div>
        </>
      )}
      {(set.error ?? map.error) && !((set.error ?? map.error) instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {(set.error ?? map.error)!.message}
        </p>
      )}
      <div className="dialog-actions">
        <Dialog.Close asChild>
          <button type="button">{t("dialog.cancel")}</button>
        </Dialog.Close>
        <button type="submit" className="primary" disabled={!ready || set.isPending}>
          {t("worldStart.set")}
        </button>
      </div>
    </form>
  );
}
