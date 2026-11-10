import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useId, useState, type FormEvent, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, EventsContext, NeedsToken, runningConversionOf, type Conversion, type ConversionEvent } from "../api";
import { useT, type Translate } from "../i18n";
import ConversionProgress from "../module/ConversionProgress";
import type { Point } from "./crs";
import type { WorldMapOwner } from "./editorApi";
import { PLACE_KINDS, ROUTE_KINDS, WATER_KINDS } from "./FeatureForm";
import {
  importGeojson,
  readPicture,
  reviewPath,
  worldMapsKey,
  type GeojsonImport,
  type NeedsScale,
  type PictureKey,
} from "./importApi";
import styles from "./WorldImport.module.css";

type Way = "geojson" | "picture";
type Units = "km" | "miles";

/** The kinds a found kind value can be mapped to, by layer; "" keeps it as it is. */
const KINDS = [...PLACE_KINDS, ...ROUTE_KINDS, ...WATER_KINDS, "region"];

export function kindLabel(t: Translate, kind: string): string {
  if ((PLACE_KINDS as readonly string[]).includes(kind)) return t(`worldMap.kind.${kind}`);
  if (kind === "region") return t("worldImport.kind.region");
  return t(`worldMapEditor.kind.${kind}`);
}

/**
 * "Import a world map": a dialog with two ways in. A GeoJSON file is imported at once; when its coordinates aren't
 * km, the server says so (`needs: "scale"`), and a mapping step shows the properties and kinds it found, with the
 * map's width or a known distance between two named places. A picture is read in the background from its key (the
 * grid and what one cell is, or with no grid two points marked on it and their distance), and its progress is shown;
 * the map then waits in review.
 */
export default function ImportWorldMap({ owner }: { owner: WorldMapOwner }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button">{t("worldImport.open")}</button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className={`dialog ${styles.dialog}`}>
          <Dialog.Title className="dialog-title">{t("worldImport.title")}</Dialog.Title>
          <Dialog.Description className="dialog-body">{t("worldImport.lede")}</Dialog.Description>
          <ImportForm owner={owner} onImported={() => setOpen(false)} />
          <div className="dialog-actions">
            <Dialog.Close asChild>
              <button type="button">{t("worldImport.close")}</button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function ImportForm({ owner, onImported }: { owner: WorldMapOwner; onImported: () => void }) {
  const t = useT();
  const id = useId();
  const client = useQueryClient();
  const [way, setWay] = useState<Way>("geojson");
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const refresh = () => client.invalidateQueries({ queryKey: worldMapsKey(owner) });

  return (
    <>
      <fieldset className={styles.ways}>
        <legend>{t("worldImport.way")}</legend>
        {(["geojson", "picture"] as const).map((w) => (
          <label key={w} className="checkbox">
            <input type="radio" name={`${id}-way`} checked={way === w} onChange={() => setWay(w)} />
            {t(`worldImport.way.${w}`)}
          </label>
        ))}
      </fieldset>
      <div className="field">
        <label htmlFor={`${id}-name`}>{t("worldImport.name")}</label>
        <input id={`${id}-name`} value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label htmlFor={`${id}-title`}>{t("worldImport.mapTitle")}</label>
        <input id={`${id}-title`} value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      {way === "geojson" ? (
        <GeojsonWay
          owner={owner}
          named={{ name: name.trim(), title: title.trim() }}
          onImported={() => {
            refresh();
            onImported();
          }}
        />
      ) : (
        <PictureWay owner={owner} named={{ name: name.trim(), title: title.trim() }} onEnded={refresh} />
      )}
    </>
  );
}

type Named = { name: string; title: string };

function GeojsonWay({ owner, named, onImported }: { owner: WorldMapOwner; named: Named; onImported: () => void }) {
  const t = useT();
  const id = useId();
  const [file, setFile] = useState<File | null>(null);
  const [needs, setNeeds] = useState<NeedsScale | null>(null);
  const [nameProp, setNameProp] = useState("");
  const [kindProp, setKindProp] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [size, setSize] = useState<"width" | "known">("width");
  const [width, setWidth] = useState("");
  const [known, setKnown] = useState({ from: "", to: "", distance: "", units: "km" as Units });
  const [unreadable, setUnreadable] = useState(false);

  const start = useMutation({
    mutationFn: async () => {
      let document: unknown;
      try {
        document = JSON.parse(await file!.text());
      } catch {
        setUnreadable(true);
        throw new Error("unreadable");
      }
      setUnreadable(false);
      const body: GeojsonImport = { ...named, document };
      if (needs) {
        const chosen = Object.fromEntries(Object.entries(values).filter(([, v]) => v));
        body.mapping = {
          ...(nameProp ? { name: nameProp } : {}),
          ...(kindProp ? { kind: kindProp } : {}),
          ...(Object.keys(chosen).length ? { values: chosen } : {}),
        };
        if (size === "width") body.width_km = Number(width);
        else body.known = { from: known.from.trim(), to: known.to.trim(), distance: Number(known.distance), units: known.units };
      }
      return importGeojson(owner, body);
    },
    onSuccess: onImported,
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422 && error.body.needs === "scale") {
        const found = error.body as unknown as NeedsScale;
        setNeeds(found);
        setNameProp((p) => p || (found.properties.includes("name") ? "name" : ""));
        setKindProp((p) => p || (found.properties.includes("kind") ? "kind" : ""));
      }
    },
  });

  const sized =
    !needs ||
    (size === "width"
      ? Number(width) > 0
      : known.from.trim() !== "" && known.to.trim() !== "" && Number(known.distance) > 0);
  const ready = file !== null && named.name !== "" && sized;
  const failed =
    start.error && !(start.error instanceof NeedsToken) && !unreadable
      ? start.error instanceof ApiError && start.error.body.needs === "scale"
        ? null
        : start.error.message
      : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ready) start.mutate();
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label htmlFor={`${id}-file`}>{t("worldImport.geojsonFile")}</label>
        <input
          id={`${id}-file`}
          type="file"
          accept=".geojson,.json,application/geo+json,application/json"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setNeeds(null);
          }}
        />
      </div>
      {needs && (
        <div className={styles.mapping}>
          <p className="notice">{needs.error}</p>
          <p className="row-meta">{t("worldImport.mappingLede")}</p>
          <div className="field">
            <label htmlFor={`${id}-name-prop`}>{t("worldImport.nameProperty")}</label>
            <select id={`${id}-name-prop`} value={nameProp} onChange={(e) => setNameProp(e.target.value)}>
              <option value="">{t("worldImport.noProperty")}</option>
              {needs.properties.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${id}-kind-prop`}>{t("worldImport.kindProperty")}</label>
            <select id={`${id}-kind-prop`} value={kindProp} onChange={(e) => setKindProp(e.target.value)}>
              <option value="">{t("worldImport.noProperty")}</option>
              {needs.properties.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          {needs.kinds.length > 0 && (
            <fieldset>
              <legend>{t("worldImport.kindsFound")}</legend>
              {needs.kinds.map((raw, i) => (
                <div className="field" key={raw}>
                  <label htmlFor={`${id}-kind-${i}`}>{raw}</label>
                  <select
                    id={`${id}-kind-${i}`}
                    value={values[raw] ?? ""}
                    onChange={(e) => setValues({ ...values, [raw]: e.target.value })}
                  >
                    <option value="">{t("worldImport.asItIs")}</option>
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {kindLabel(t, k)}
                      </option>
                    ))}
                  </select>
                </div>
              ))}
            </fieldset>
          )}
          <fieldset>
            <legend>{t("worldImport.size")}</legend>
            <label className="checkbox">
              <input type="radio" name={`${id}-size`} checked={size === "width"} onChange={() => setSize("width")} />
              {t("worldImport.size.width")}
            </label>
            <label className="checkbox">
              <input type="radio" name={`${id}-size`} checked={size === "known"} onChange={() => setSize("known")} />
              {t("worldImport.size.known")}
            </label>
          </fieldset>
          {size === "width" ? (
            <div className="field">
              <label htmlFor={`${id}-width`}>{t("worldImport.widthKm")}</label>
              <input
                id={`${id}-width`}
                type="number"
                min="0"
                step="any"
                value={width}
                onChange={(e) => setWidth(e.target.value)}
              />
            </div>
          ) : (
            <div className="inline-form">
              <div className="field">
                <label htmlFor={`${id}-from`}>{t("worldImport.from")}</label>
                <input id={`${id}-from`} value={known.from} onChange={(e) => setKnown({ ...known, from: e.target.value })} />
              </div>
              <div className="field">
                <label htmlFor={`${id}-to`}>{t("worldImport.to")}</label>
                <input id={`${id}-to`} value={known.to} onChange={(e) => setKnown({ ...known, to: e.target.value })} />
              </div>
              <Distance
                id={id}
                distance={known.distance}
                units={known.units}
                onChange={(distance, units) => setKnown({ ...known, distance, units })}
              />
            </div>
          )}
        </div>
      )}
      {unreadable && (
        <p role="alert" className="notice error">
          {t("worldImport.unreadable")}
        </p>
      )}
      {failed && (
        <p role="alert" className="notice error">
          {t("worldImport.failed", { error: failed })}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="primary" disabled={!ready || start.isPending}>
          {t("worldImport.import")}
        </button>
      </div>
    </form>
  );
}

function Distance({
  id,
  distance,
  units,
  onChange,
}: {
  id: string;
  distance: string;
  units: Units;
  onChange: (distance: string, units: Units) => void;
}) {
  const t = useT();
  return (
    <>
      <div className="field">
        <label htmlFor={`${id}-distance`}>{t("worldImport.distance")}</label>
        <input
          id={`${id}-distance`}
          type="number"
          min="0"
          step="any"
          value={distance}
          onChange={(e) => onChange(e.target.value, units)}
        />
      </div>
      <div className="field">
        <label htmlFor={`${id}-units`}>{t("worldImport.units")}</label>
        <select id={`${id}-units`} value={units} onChange={(e) => onChange(distance, e.target.value as Units)}>
          <option value="km">{t("worldMapEditor.units.km")}</option>
          <option value="miles">{t("worldMapEditor.units.miles")}</option>
        </select>
      </div>
    </>
  );
}

function PictureWay({ owner, named, onEnded }: { owner: WorldMapOwner; named: Named; onEnded: () => void }) {
  const t = useT();
  const id = useId();
  const subscribe = useContext(EventsContext);
  const [file, setFile] = useState<File | null>(null);
  const [cell, setCell] = useState<PictureKey["cell"]>("hex");
  const [distance, setDistance] = useState("");
  const [units, setUnits] = useState<Units>("km");
  const [points, setPoints] = useState<Point[]>([]);
  const [refused, setRefused] = useState(false);
  const [started, setStarted] = useState<Conversion | null>(null);
  const [ended, setEnded] = useState<ConversionEvent["status"] | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  // The picture is shown only to mark its two points; its object URL is let go with it.
  useEffect(() => {
    if (!file || cell !== "none" || typeof URL.createObjectURL !== "function") return setPreview(null);
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file, cell]);

  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (!started || event?.id !== started.id || event.status === "running") return;
          setEnded(event.status);
          onEnded();
        },
      }),
    [subscribe, started, onEnded],
  );

  const start = useMutation({
    mutationFn: () =>
      readPicture(owner, file!, {
        ...named,
        cell,
        distance: Number(distance),
        units,
        ...(cell === "none" ? { points: [points[0], points[1]] as [Point, Point] } : {}),
      }),
    onSuccess: setStarted,
    onError: (error) => {
      const running = runningConversionOf(error);
      if (running) setStarted(running);
    },
  });

  function mark(e: MouseEvent<HTMLImageElement>) {
    const shown = e.currentTarget;
    const box = shown.getBoundingClientRect();
    const scale = shown.naturalWidth && box.width ? shown.naturalWidth / box.width : 1;
    const at: Point = [(e.clientX - box.left) * scale, (e.clientY - box.top) * scale];
    setPoints((marked) => (marked.length >= 2 ? [at] : [...marked, at]));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!(Number(distance) > 0) || (cell === "none" && points.length < 2)) {
      setRefused(true);
      return;
    }
    setRefused(false);
    start.mutate();
  }

  const failed = start.error && !(start.error instanceof NeedsToken) && !runningConversionOf(start.error);

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label htmlFor={`${id}-file`}>{t("worldImport.picture")}</label>
        <input
          id={`${id}-file`}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setPoints([]);
          }}
        />
      </div>
      <div className="inline-form">
        <div className="field">
          <label htmlFor={`${id}-cell`}>{t("worldImport.grid")}</label>
          <select id={`${id}-cell`} value={cell} onChange={(e) => setCell(e.target.value as PictureKey["cell"])}>
            {(["hex", "square", "none"] as const).map((c) => (
              <option key={c} value={c}>
                {t(`worldImport.grid.${c}`)}
              </option>
            ))}
          </select>
        </div>
        <p className="row-meta">{t(cell === "none" ? "worldImport.keyPoints" : `worldImport.keyCell.${cell}`)}</p>
        <Distance
          id={id}
          distance={distance}
          units={units}
          onChange={(d, u) => {
            setDistance(d);
            setUnits(u);
          }}
        />
      </div>
      {cell === "none" && file && (
        <div className={styles.points}>
          <img
            src={preview ?? undefined}
            alt={t("worldImport.markPoints")}
            role="img"
            onClick={mark}
          />
          <p className="row-meta">{t("worldImport.pointsMarked", { count: String(points.length) })}</p>
        </div>
      )}
      {refused && (
        <p role="alert" className="notice error">
          {t(cell === "none" && points.length < 2 ? "worldImport.needsPoints" : "worldImport.needsDistance")}
        </p>
      )}
      {failed && (
        <p role="alert" className="notice error">
          {t("worldImport.failed", { error: start.error!.message })}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="primary" disabled={!file || named.name === "" || start.isPending || !!started}>
          {t("worldImport.start")}
        </button>
      </div>
      {started && <ConversionProgress key={started.id} conversion={started} />}
      {started && ended === "done" && (
        <Link className="button-like primary" to={reviewPath(owner, started.target?.name ?? named.name)}>
          {t("worldImport.review")}
        </Link>
      )}
    </form>
  );
}
