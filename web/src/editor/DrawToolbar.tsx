// Toolbar for the map editor's drawing tools and the tracing-reference image.
import { useRef, type ChangeEvent } from "react";
import type { Tool } from "./lib/draw";
import { useT } from "../i18n";
import { Icon } from "./icons";
import { FeatureSelect } from "./FeatureSelect";
import styles from "./DrawToolbar.module.css";

// Each tool's label and hint are editor.tool.<id> and editor.tool.<id>.hint.
const TOOLS: Tool[] = [
  "select",
  "rect",
  "circle",
  "polygon",
  "cave",
  "corridor",
  "door",
  "feature",
  "text",
  "area",
  "line",
  "exit",
];

// Built-in terrain kinds for the area tool (mirror the renderer palette).
const AREA_KINDS = ["water", "lava", "pit", "chasm", "mud", "acid", "ice", "blood", "slime", "swamp"];
// Line-feature styles (mirror the renderer): bars=dotted, curtain=wavy, barred=+, step=2 thin lines.
const LINE_KINDS = ["bars", "curtain", "barred", "step", "stream", "canal", "bridge"];

const DOOR_TYPES = ["wooden", "open", "double", "one-way", "arch", "gates", "portcullis", "iron", "stone", "secret", "concealed", "smashed"];
const DOOR_STATES = ["closed", "open", "locked"];
const DOOR_FACINGS = ["auto", "north", "south", "east", "west"];

// Fallback feature list shown until the backend reports which feature_defs
// the map's includes actually resolve to (see `featureTypes` prop).
const FALLBACK_FEATURE_TYPES = [
  "pit-trap", "dart-trap", "fire-trap", "portcullis", "pillar", "altar",
  "statue", "fountain", "brazier", "chest", "rubble", "water", "bridge",
  "stairs-up", "stairs-down", "stairs-left", "stairs-right", "stairs-spiral",
].sort((a, b) => a.localeCompare(b));

export function DrawToolbar({
  tool,
  onTool,
  snap,
  onSnap,
  snapResolution,
  onSnapResolution,
  bgImage,
  onBgImage,
  bgOpacity,
  onBgOpacity,
  doorType,
  onDoorType,
  doorState,
  onDoorState,
  doorFacing,
  onDoorFacing,
  doorTrapped,
  onDoorTrapped,
  featureType,
  onFeatureType,
  featureTypes,
  featureGroups,
  featureRotate,
  onFeatureRotate,
  featureScale,
  onFeatureScale,
  featureGlobal,
  onFeatureGlobal,
  corridorOrganic,
  onCorridorOrganic,
  corridorStraight,
  onCorridorStraight,
  textContent,
  onTextContent,
  textSize,
  onTextSize,
  textDescription,
  onTextDescription,
  textGlobal,
  onTextGlobal,
  areaKind,
  onAreaKind,
  areaOrganic,
  onAreaOrganic,
  lineKind,
  onLineKind,
  exitTargetMap,
  onExitTargetMap,
  exitMapOptions,
  exitTargetX,
  onExitTargetX,
  exitTargetY,
  onExitTargetY,
  exitLabel,
  onExitLabel,
  exitSecret,
  onExitSecret,
  exitGlobal,
  onExitGlobal,
  pathCheck,
  onPathCheck,
  connectionsMode,
  onConnectionsMode,
  cellGrid,
  onCellGrid,
  onSort,
  disabled,
}: {
  tool: Tool;
  onTool: (t: Tool) => void;
  snap: boolean;
  onSnap: (s: boolean) => void;
  snapResolution: number;
  onSnapResolution: (n: number) => void;
  bgImage: string | null;
  onBgImage: (img: string | null) => void;
  bgOpacity: number;
  onBgOpacity: (o: number) => void;
  doorType: string;
  onDoorType: (t: string) => void;
  doorState: string;
  onDoorState: (s: string) => void;
  doorFacing: string;
  onDoorFacing: (f: string) => void;
  doorTrapped: boolean;
  onDoorTrapped: (v: boolean) => void;
  featureType: string;
  onFeatureType: (t: string) => void;
  featureTypes: string[];
  featureGroups: { source: string; names: string[] }[];
  featureRotate: number;
  onFeatureRotate: (n: number) => void;
  featureScale: number;
  onFeatureScale: (n: number) => void;
  featureGlobal: boolean;
  onFeatureGlobal: (v: boolean) => void;
  corridorOrganic: boolean;
  onCorridorOrganic: (v: boolean) => void;
  corridorStraight: boolean;
  onCorridorStraight: (v: boolean) => void;
  textContent: string;
  onTextContent: (v: string) => void;
  textSize: number;
  onTextSize: (n: number) => void;
  textDescription: string;
  onTextDescription: (v: string) => void;
  textGlobal: boolean;
  onTextGlobal: (v: boolean) => void;
  areaKind: string;
  onAreaKind: (v: string) => void;
  areaOrganic: boolean;
  onAreaOrganic: (v: boolean) => void;
  lineKind: string;
  onLineKind: (v: string) => void;
  exitTargetMap: string;
  onExitTargetMap: (v: string) => void;
  exitMapOptions: string[];
  exitTargetX: number;
  onExitTargetX: (n: number) => void;
  exitTargetY: number;
  onExitTargetY: (n: number) => void;
  exitLabel: string;
  onExitLabel: (v: string) => void;
  exitSecret: boolean;
  onExitSecret: (v: boolean) => void;
  exitGlobal: boolean;
  onExitGlobal: (v: boolean) => void;
  pathCheck: boolean;
  onPathCheck: (p: boolean) => void;
  connectionsMode: boolean;
  onConnectionsMode: (v: boolean) => void;
  cellGrid: boolean;
  onCellGrid: (v: boolean) => void;
  onSort: () => void;
  disabled?: boolean;
}) {
  const t = useT();
  const fileRef = useRef<HTMLInputElement>(null);
  const active = TOOLS.includes(tool) ? tool : TOOLS[0];
  const features = featureTypes.length ? featureTypes : FALLBACK_FEATURE_TYPES;

  function onPick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onBgImage(typeof reader.result === "string" ? reader.result : null);
    reader.readAsDataURL(file);
    e.target.value = ""; // allow re-picking the same file later
  }

  return (
    <div className={styles.bar} aria-disabled={disabled}>
      <div className={styles.group} role="group" aria-label={t("editor.tools")}>
        {TOOLS.map((id) => (
          <button
            key={id}
            type="button"
            className={`${styles.tool} ${tool === id ? styles.toolActive : ""}`}
            onClick={() => onTool(id)}
            disabled={disabled}
            title={`${t(`editor.tool.${id}`)} — ${t(`editor.tool.${id}.hint`)}`}
            aria-pressed={tool === id}
          >
            <Icon name={id} />
          </button>
        ))}
      </div>

      <label className={styles.snap} title={t("editor.snap.hint")}>
        <input
          type="checkbox"
          checked={snap}
          onChange={(e) => onSnap(e.target.checked)}
          disabled={disabled}
        />
        {t("editor.snap")}
      </label>

      {snap ? (
        <label
          className={styles.numField}
          title={t("editor.res.hint")}
        >
          {t("editor.res")}
          <input
            type="number"
            className={styles.num}
            value={snapResolution}
            min={1}
            step={1}
            onChange={(e) =>
              onSnapResolution(Math.max(1, Math.round(Number(e.target.value) || 1)))
            }
            disabled={disabled}
          />
        </label>
      ) : null}

      <label
        className={styles.snap}
        title={t("editor.pathing.hint")}
      >
        <input
          type="checkbox"
          checked={pathCheck}
          onChange={(e) => onPathCheck(e.target.checked)}
          disabled={disabled}
        />
        {t("editor.pathing")}
      </label>

      <label
        className={styles.snap}
        title={t("editor.connections.hint")}
      >
        <input
          type="checkbox"
          checked={connectionsMode}
          onChange={(e) => onConnectionsMode(e.target.checked)}
          disabled={disabled}
        />
        {t("editor.connections")}
      </label>

      <label
        className={styles.snap}
        title={t("editor.cellGrid.hint")}
      >
        <input
          type="checkbox"
          checked={cellGrid}
          onChange={(e) => onCellGrid(e.target.checked)}
          disabled={disabled}
        />
        {t("editor.cellGrid")}
      </label>

      {tool === "door" ? (
        <div className={styles.group} role="group" aria-label={t("editor.door.options")}>
          <select
            className={styles.select}
            value={doorType}
            onChange={(e) => onDoorType(e.target.value)}
            disabled={disabled}
            title={t("editor.door.type")}
          >
            {DOOR_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={doorState}
            onChange={(e) => onDoorState(e.target.value)}
            disabled={disabled || doorType === "arch" || doorType === "open"}
            title={
              doorType === "arch" || doorType === "open"
                ? t("editor.door.noState")
                : t("editor.door.state")
            }
          >
            {DOOR_STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            className={styles.select}
            value={doorFacing}
            onChange={(e) => onDoorFacing(e.target.value)}
            disabled={disabled}
            title={t("editor.door.facing")}
          >
            {DOOR_FACINGS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <label
            className={styles.snap}
            title={t("editor.door.trapped.hint")}
          >
            <input
              type="checkbox"
              checked={doorTrapped}
              onChange={(e) => onDoorTrapped(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.door.trapped")}
          </label>
        </div>
      ) : null}

      {tool === "feature" ? (
        <div className={styles.group} role="group" aria-label={t("editor.feature.options")}>
          <FeatureSelect
            value={featureType}
            onChange={onFeatureType}
            groups={featureGroups}
            fallback={features}
            disabled={disabled}
          />
          <label className={styles.numField} title={t("editor.feature.rotate")}>
            ⟳
            <input
              type="number"
              className={styles.num}
              value={featureRotate}
              step={15}
              onChange={(e) => onFeatureRotate(Number(e.target.value) || 0)}
              disabled={disabled}
            />
          </label>
          <label className={styles.numField} title={t("editor.feature.scale")}>
            ⤢
            <input
              type="number"
              className={styles.num}
              value={featureScale}
              step={0.25}
              min={0.1}
              onChange={(e) => onFeatureScale(Number(e.target.value) || 1)}
              disabled={disabled}
            />
          </label>
          <label
            className={styles.snap}
            title={t("editor.feature.global.hint")}
          >
            <input
              type="checkbox"
              checked={featureGlobal}
              onChange={(e) => onFeatureGlobal(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.global")}
          </label>
        </div>
      ) : null}

      {tool === "corridor" ? (
        <>
          <label
            className={styles.snap}
            title={t("editor.corridor.organic.hint")}
          >
            <input
              type="checkbox"
              checked={corridorOrganic}
              onChange={(e) => onCorridorOrganic(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.organic")}
          </label>
          <label
            className={styles.snap}
            title={t("editor.corridor.straight.hint")}
          >
            <input
              type="checkbox"
              checked={corridorStraight}
              onChange={(e) => onCorridorStraight(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.corridor.straight")}
          </label>
        </>
      ) : null}

      {tool === "text" ? (
        <div className={styles.group} role="group" aria-label={t("editor.text.options")}>
          <input
            type="text"
            className={styles.select}
            value={textContent}
            placeholder={t("editor.text.placeholder")}
            onChange={(e) => onTextContent(e.target.value)}
            disabled={disabled}
            title={t("editor.text.content")}
          />
          <label className={styles.numField} title={t("editor.text.size")}>
            A
            <input
              type="number"
              className={styles.num}
              value={textSize}
              step={0.25}
              min={0.1}
              onChange={(e) => onTextSize(Number(e.target.value) || 1)}
              disabled={disabled}
            />
          </label>
          <input
            type="text"
            className={styles.select}
            value={textDescription}
            placeholder={t("editor.text.description")}
            onChange={(e) => onTextDescription(e.target.value)}
            disabled={disabled}
            title={t("editor.text.description.hint")}
          />
          <label
            className={styles.snap}
            title={t("editor.text.global.hint")}
          >
            <input
              type="checkbox"
              checked={textGlobal}
              onChange={(e) => onTextGlobal(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.global")}
          </label>
        </div>
      ) : null}

      {tool === "area" ? (
        <div className={styles.group} role="group" aria-label={t("editor.area.options")}>
          <select
            className={styles.select}
            value={areaKind}
            onChange={(e) => onAreaKind(e.target.value)}
            disabled={disabled}
            title={t("editor.area.kind")}
          >
            {AREA_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <label className={styles.snap} title={t("editor.area.organic.hint")}>
            <input
              type="checkbox"
              checked={areaOrganic}
              onChange={(e) => onAreaOrganic(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.organic")}
          </label>
        </div>
      ) : null}

      {tool === "line" ? (
        <div className={styles.group} role="group" aria-label={t("editor.line.options")}>
          <select
            className={styles.select}
            value={lineKind}
            onChange={(e) => onLineKind(e.target.value)}
            disabled={disabled}
            title={t("editor.line.kind")}
          >
            {LINE_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {tool === "exit" ? (
        <div className={styles.group} role="group" aria-label={t("editor.exit.options")}>
          <select
            className={styles.select}
            value={exitTargetMap}
            onChange={(e) => onExitTargetMap(e.target.value)}
            disabled={disabled}
            title={t("editor.exit.map")}
          >
            <option value="">{t("editor.exit.mapPlaceholder")}</option>
            {/* The current value may name a map that isn't in the list (e.g.
                renamed/deleted, or hand-typed in the editor) — keep it
                selectable so the dropdown still reflects the source. */}
            {exitTargetMap && !exitMapOptions.includes(exitTargetMap) ? (
              <option value={exitTargetMap}>{exitTargetMap}</option>
            ) : null}
            {exitMapOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <label className={styles.numField} title={t("editor.exit.x")}>
            →X
            <input
              type="number"
              className={styles.num}
              value={exitTargetX}
              step={1}
              onChange={(e) => onExitTargetX(Number(e.target.value) || 0)}
              disabled={disabled}
            />
          </label>
          <label className={styles.numField} title={t("editor.exit.y")}>
            →Y
            <input
              type="number"
              className={styles.num}
              value={exitTargetY}
              step={1}
              onChange={(e) => onExitTargetY(Number(e.target.value) || 0)}
              disabled={disabled}
            />
          </label>
          <input
            type="text"
            className={styles.select}
            value={exitLabel}
            placeholder={t("editor.exit.label")}
            onChange={(e) => onExitLabel(e.target.value)}
            disabled={disabled}
            title={t("editor.exit.label.hint")}
          />
          <label
            className={styles.snap}
            title={t("editor.exit.secret.hint")}
          >
            <input
              type="checkbox"
              checked={exitSecret}
              onChange={(e) => onExitSecret(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.exit.secret")}
          </label>
          <label
            className={styles.snap}
            title={t("editor.exit.global.hint")}
          >
            <input
              type="checkbox"
              checked={exitGlobal}
              onChange={(e) => onExitGlobal(e.target.checked)}
              disabled={disabled}
            />
            {t("editor.global")}
          </label>
        </div>
      ) : null}

      <div className={styles.spacer} />

      <button
        type="button"
        className={styles.sortBtn}
        onClick={onSort}
        title={t("editor.sort.hint")}
      >
        <Icon name="sort" size={15} />
        {t("editor.sort")}
      </button>

      <div className={styles.group} role="group" aria-label={t("editor.reference")}>
        <button
          type="button"
          className={styles.refBtn}
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          title={t("editor.reference.hint")}
        >
          {bgImage ? t("editor.reference.replace") : t("editor.reference.load")}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          hidden
          onChange={onPick}
        />
        {bgImage ? (
          <>
            <input
              className={styles.slider}
              type="range"
              min={0}
              max={100}
              value={Math.round(bgOpacity * 100)}
              onChange={(e) => onBgOpacity(Number(e.target.value) / 100)}
              title={t("editor.reference.opacity")}
              aria-label={t("editor.reference.opacity")}
            />
            <button
              type="button"
              className={styles.refBtn}
              onClick={() => onBgImage(null)}
              title={t("editor.reference.clear.hint")}
            >
              {t("editor.reference.clear")}
            </button>
          </>
        ) : null}
      </div>

      <span className={styles.hint}>{t(`editor.tool.${active}.hint`)}</span>
    </div>
  );
}
