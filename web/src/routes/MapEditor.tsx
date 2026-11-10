import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Link,
  useBlocker,
  useNavigate,
  useParams,
  type BlockerFunction,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "../api";
import { ApiError, attachmentUrl } from "../api";
import type {
  Diagnostic,
  FeatureGroup,
  MapDetail,
  NodeConnectivity,
  ParseErrorBody,
  RenderResponse,
  SimplifyResponse,
} from "../editor/types";
import { useDebounce } from "../editor/useDebounce";
import type { CursorPos } from "../editor/lib/sourceAnchor";
import { Button } from "../editor/Primitives";
import { MonacoEditor } from "../editor/MonacoEditor";
import { SvgPreview } from "../editor/SvgPreview";
import Split from "../desktop/Split";
import { usePhone } from "../play/usePhone";
import { DrawToolbar } from "../editor/DrawToolbar";
import { DiagnosticsPanel } from "../editor/DiagnosticsPanel";
import { SimplifyDialog } from "../editor/SimplifyDialog";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import {
  emitShape,
  findDefinition,
  hasCellGrid,
  insertSnippetInRegion,
  setCellGrid,
  sortSource,
  type DraftShape,
  type Tool,
} from "../editor/lib/draw";
import styles from "./MapEditor.module.css";
import { starterMap } from "../editor/lib/starter";
import ProvenanceNotice, { provenanceOf } from "../module/ProvenanceNotice";

/**
 * `/maps/:moduleId/:mapName`: the map editor, ported from dungml's MapEditorPage. At
 * `/campaigns/:campaignId/own-maps/:mapName` it edits a campaign's own map (campaign maps, 2026-10-23) through the
 * campaign's routes: its includes come from the module's libraries, its exits lead to the campaign's other maps, its
 * crumb goes back to the campaign, and it has no print view.
 */
export default function MapEditor() {
  const params = useParams();
  const campaignId = params.campaignId ?? "";
  const own = !!campaignId;
  const mapName = params.mapName ?? "";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const t = useT();

  const { data: map, isLoading, error: loadError } = useQuery<MapDetail>({
    queryKey: own ? api.queryKeys.ownMap(campaignId, mapName) : api.queryKeys.map(params.moduleId ?? "", mapName),
    queryFn: () =>
      own
        ? (api.getOwnMap(campaignId, mapName) as Promise<unknown> as Promise<MapDetail>)
        : api.getMap(params.moduleId ?? "", mapName),
    enabled: (own || !!params.moduleId) && !!mapName,
  });
  const moduleId = own ? (map?.module_id ?? "") : (params.moduleId ?? "");
  // Where a map's per-browser editor state is kept.
  const mapKey = own ? `campaign:${campaignId}/${mapName}` : `${moduleId}/${mapName}`;
  // The calls the editor makes for this map: the module's routes, or the campaign's for its own map.
  const target = useMemo(
    () =>
      own
        ? {
            render: (source: string) => api.renderOwnMap(campaignId, mapName, source),
            featureNames: (source: string) => api.ownMapFeatureNames(campaignId, mapName, source),
            simplify: (source: string, doorSpurs: boolean) => api.simplifyOwnMap(campaignId, mapName, source, doorSpurs),
            save: (source: string) => api.putOwnMap(campaignId, mapName, { source }) as Promise<{ source: string }>,
          }
        : {
            render: (source: string) => api.renderMap(moduleId, mapName, source),
            featureNames: (source: string) => api.mapFeatureNames(moduleId, mapName, source),
            simplify: (source: string, doorSpurs: boolean) => api.simplifyMap(moduleId, mapName, source, doorSpurs),
            save: (source: string) => api.putMap(moduleId, mapName, { source }) as Promise<{ source: string }>,
          },
    [own, campaignId, moduleId, mapName],
  );

  // The other maps the exit tool can target: the module's (renderable maps, not its libraries), or for a campaign's
  // own map every map the campaign plays; never this map itself.
  const { data: module } = useQuery({
    queryKey: api.queryKeys.module(moduleId),
    queryFn: () => api.getModule(moduleId),
    enabled: !!moduleId && !own,
  });
  const { data: campaign } = useQuery({
    queryKey: api.queryKeys.campaign(campaignId),
    queryFn: () => api.getCampaign(campaignId),
    enabled: own,
  });
  const exitMapOptions = own
    ? (campaign?.maps ?? []).filter((m) => m !== mapName)
    : (module?.maps ?? []).filter((m) => m.role !== "library" && m.name !== mapName).map((m) => m.name);

  const [source, setSource] = useState<string>("");
  const [lastSaved, setLastSaved] = useState<string>("");
  // The source a Save just stored: the map read again after it is that source, and leaves the editor alone, so what
  // was typed while it saved stays (DEL-174).
  const justSaved = useRef<string | null>(null);
  // Initialize editor contents when the map loads (or changes). An empty map opens with a starter map, unsaved.
  useEffect(() => {
    if (!map) return;
    if (justSaved.current !== null && map.source === justSaved.current) {
      justSaved.current = null;
      return;
    }
    setSource(map.role === "map" && !map.source.trim() ? starterMap(map.name) : map.source);
    setLastSaved(map.source);
  }, [map]);

  const dirty = source !== lastSaved;

  // --- drawing tools + tracing reference (editor-only, never saved to .dmap) ---
  const [tool, setTool] = useState<Tool>("select");
  const [snap, setSnap] = useState(true);
  const [snapResolution, setSnapResolution] = useState(1);
  const [bgImage, setBgImage] = useState<string | null>(null);
  const [bgOpacity, setBgOpacity] = useState(0.5);
  const [doorType, setDoorType] = useState("wooden");
  const [doorState, setDoorState] = useState("closed");
  const [doorFacing, setDoorFacing] = useState("auto");
  const [doorTrapped, setDoorTrapped] = useState(false);
  const [featureType, setFeatureType] = useState("pit-trap");
  const [featureRotate, setFeatureRotate] = useState(0);
  const [featureScale, setFeatureScale] = useState(1);
  const [featureGlobal, setFeatureGlobal] = useState(false);
  // Feature types available to this map — the feature_defs its includes
  // resolve to (plus any defined locally). `featureTypes` is the flat list
  // (for default-selection); `featureGroups` splits them by source file for
  // the grouped dropdown. Populated from the backend.
  const [featureTypes, setFeatureTypes] = useState<string[]>([]);
  const [featureGroups, setFeatureGroups] = useState<FeatureGroup[]>([]);
  const [corridorOrganic, setCorridorOrganic] = useState(false);
  const [corridorStraight, setCorridorStraight] = useState(false);
  const [textContent, setTextContent] = useState("");
  const [textSize, setTextSize] = useState(1);
  const [textDescription, setTextDescription] = useState("");
  const [textGlobal, setTextGlobal] = useState(false);
  const [areaKind, setAreaKind] = useState("water");
  const [areaOrganic, setAreaOrganic] = useState(true);
  const [lineKind, setLineKind] = useState("bars");
  const [exitTargetMap, setExitTargetMap] = useState("");
  const [exitTargetX, setExitTargetX] = useState(0);
  const [exitTargetY, setExitTargetY] = useState(0);
  const [exitLabel, setExitLabel] = useState("");
  const [exitSecret, setExitSecret] = useState(false);
  const [exitGlobal, setExitGlobal] = useState(false);
  const [pathCheck, setPathCheck] = useState(false);
  const [connectionsMode, setConnectionsMode] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // On a phone the code and the drawing are two tabs; both stay mounted, so Monaco keeps its cursor and undo.
  const phone = usePhone();
  const [pane, setPane] = useState<"code" | "drawing">("code");
  // A drafted map's book page, shown beside the canvas (under it on narrower screens) to compare the drawing with.
  const [pageShown, setPageShown] = useState(false);
  const bookPage = pageShown ? (provenanceOf(source)?.page ?? null) : null;

  const [wordWrap, setWordWrap] = useState<boolean>(() => {
    try {
      return localStorage.getItem("delve.editor.wrap") === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("delve.editor.wrap", wordWrap ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
  }, [wordWrap]);
  const [connectivity, setConnectivity] = useState<NodeConnectivity[] | null>(
    null,
  );
  const traceKey = moduleId && mapName ? `delve.editor.trace.${mapKey}` : "";

  // Load any saved tracing reference for this map from the browser.
  useEffect(() => {
    if (!traceKey) return;
    setBgImage(null);
    setBgOpacity(0.5);
    try {
      const raw = localStorage.getItem(traceKey);
      if (raw) {
        const v = JSON.parse(raw) as { image?: string; opacity?: number };
        if (v.image) setBgImage(v.image);
        if (typeof v.opacity === "number") setBgOpacity(v.opacity);
      }
    } catch {
      /* ignore malformed/unavailable storage */
    }
  }, [traceKey]);

  // Persist the reference per-map (best-effort — a large image may exceed the
  // storage quota, in which case it simply stays in-session).
  useEffect(() => {
    if (!traceKey) return;
    try {
      if (bgImage) {
        localStorage.setItem(
          traceKey,
          JSON.stringify({ image: bgImage, opacity: bgOpacity }),
        );
      } else {
        localStorage.removeItem(traceKey);
      }
    } catch {
      /* quota exceeded or storage disabled — overlay still works this session */
    }
  }, [traceKey, bgImage, bgOpacity]);

  // A completed shape becomes a .dmap block appended to the source. A feature
  // or exit dropped on a room/corridor is nested inside that block instead (the
  // preview sets `region`); if the block can't be located we fall back to
  // appending.
  const onEmit = useCallback((shape: DraftShape) => {
    setSource((s) => {
      const snippet = emitShape(s, shape);
      const region =
        shape.kind === "feature" ||
        shape.kind === "exit" ||
        shape.kind === "text"
          ? shape.region
          : null;
      if (region) {
        const nested = insertSnippetInRegion(s, region, snippet);
        if (nested) return nested;
      }
      return s + snippet;
    });
  }, []);

  // Where the editor cursor is — the map highlights the entity under it.
  const [cursor, setCursor] = useState<CursorPos | null>(null);

  // Jump-to-definition: reveal a line in the editor (nonce forces re-trigger).
  const [goto, setGoto] = useState<{
    line: number;
    column: number;
    nonce: number;
  } | null>(null);

  const onPick = useCallback(
    (kind: "room" | "corridor", name: string) => {
      // Connections mode: clicking a node lists its doors. Otherwise jump to
      // the node's definition in the editor.
      if (connectionsMode) {
        setSelectedNode(`${kind}.${name}`);
        return;
      }
      const def = findDefinition(source, kind, name);
      if (def) setGoto((g) => ({ ...def, nonce: (g?.nonce ?? 0) + 1 }));
    },
    [source, connectionsMode],
  );

  const onJump = useCallback((d: Diagnostic) => {
    if (d.line > 0)
      setGoto((g) => ({
        line: d.line,
        column: Math.max(1, d.column),
        nonce: (g?.nonce ?? 0) + 1,
      }));
  }, []);

  // Simplify: ask the backend for a geometry-preserving rewrite of the live
  // buffer, review it in a dialog, then apply it to the buffer (undoable, not
  // saved). The result is tied to the buffer it was computed from.
  const [simplifyOpen, setSimplifyOpen] = useState(false);
  const [simplifyDoorSpurs, setSimplifyDoorSpurs] = useState(false);
  const [simplifyResult, setSimplifyResult] = useState<{
    for: string;
    result: SimplifyResponse;
  } | null>(null);
  const [simplifyError, setSimplifyError] = useState<string | null>(null);
  const [simplifyLoading, setSimplifyLoading] = useState(false);
  const runSimplify = useCallback(
    (doorSpurs: boolean) => {
      setSimplifyLoading(true);
      setSimplifyError(null);
      const buffer = source;
      target
        .simplify(buffer, doorSpurs)
        .then((result) => setSimplifyResult({ for: buffer, result }))
        .catch((e: unknown) => {
          setSimplifyResult(null);
          setSimplifyError(
            e instanceof ApiError ? e.message : String((e as Error)?.message ?? e),
          );
        })
        .finally(() => setSimplifyLoading(false));
    },
    [target, source],
  );
  const openSimplify = useCallback(() => {
    setSimplifyOpen(true);
    runSimplify(simplifyDoorSpurs);
  }, [runSimplify, simplifyDoorSpurs]);
  const applySimplify = useCallback(() => {
    if (!simplifyResult) return;
    // Only apply onto the exact buffer it was computed from.
    setSource((s) => (s === simplifyResult.for ? simplifyResult.result.source : s));
    setSimplifyOpen(false);
  }, [simplifyResult]);

  // Live preview — debounced render call against the map's render route so
  // `include "core.dmap"` resolves to the module's own library maps first.
  const debouncedSource = useDebounce(source, 350);
  const [preview, setPreview] = useState<RenderResponse | null>(null);
  const [renderError, setRenderError] = useState<{
    message: string;
    line?: number;
    column?: number;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const renderSeq = useRef(0);

  // Library files (no top-level `map "..." { }` block) are not
  // renderable — they're included by other maps. Detect early and skip
  // the render call so the editor doesn't keep flashing a parse error.
  const isLibrary = !/\bmap\s+"/.test(debouncedSource);

  useEffect(() => {
    if (!debouncedSource) {
      setPreview(null);
      setRenderError(null);
      return;
    }
    if (isLibrary) {
      setPreview(null);
      setRenderError(null);
      setPreviewLoading(false);
      return;
    }
    const seq = ++renderSeq.current;
    setPreviewLoading(true);
    target
      .render(debouncedSource)
      .then((r) => {
        if (seq !== renderSeq.current) return;
        setPreview(r);
        setRenderError(null);
      })
      .catch((e) => {
        if (seq !== renderSeq.current) return;
        if (e instanceof ApiError && e.status === 400) {
          setRenderError(parseError(e));
        } else {
          setRenderError({ message: String(e?.message ?? e) });
        }
      })
      .finally(() => {
        if (seq === renderSeq.current) setPreviewLoading(false);
      });
  }, [debouncedSource, target]);

  // Available feature types for the dropdown — refreshed when the source
  // changes (e.g. an `include` is added/removed). Keeps the last good list
  // on parse errors so the dropdown doesn't flicker empty mid-edit.
  useEffect(() => {
    if (!moduleId || !mapName || !debouncedSource) return;
    let cancelled = false;
    target
      .featureNames(debouncedSource)
      .then((r) => {
        if (cancelled || r.names.length === 0) return;
        setFeatureTypes(r.names);
        setFeatureGroups(r.groups);
        // If the current pick is no longer offered, snap to the first.
        setFeatureType((cur) => (r.names.includes(cur) ? cur : r.names[0]));
      })
      .catch(() => {
        /* keep the last good list */
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSource, moduleId, mapName]);

  // Fetch per-node connectivity while pathing-check or connections mode is on.
  useEffect(() => {
    if ((!pathCheck && !connectionsMode) || !debouncedSource || isLibrary) {
      setConnectivity(null);
      return;
    }
    let cancelled = false;
    api.dsl
      .connectivity(debouncedSource, moduleId)
      .then((r) => {
        if (!cancelled) setConnectivity(r.nodes);
      })
      .catch(() => {
        if (!cancelled) setConnectivity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [pathCheck, connectionsMode, debouncedSource, isLibrary, moduleId]);

  // Diagnostics shown in the panel come from a successful render. On a
  // parse error we synthesize a single error diagnostic so the user
  // still sees the squiggle and the message in the panel.
  const diagnostics: Diagnostic[] = renderError
    ? [
        {
          severity: "error",
          message: renderError.message,
          line: renderError.line ?? 0,
          column: renderError.column ?? 0,
          end_line: renderError.line ?? 0,
          end_column: (renderError.column ?? 0) + 1,
        },
      ]
    : preview?.diagnostics ?? [];

  // Save mutation — explicit save action, not autosave. A source that
  // doesn't parse is refused (400) and shows like a render's parse error.
  const save = useMutation({
    mutationFn: () => target.save(source),
    onSuccess: (m) => {
      justSaved.current = m.source;
      setLastSaved(m.source);
      if (own) {
        qc.invalidateQueries({ queryKey: api.queryKeys.ownMaps(campaignId) });
        qc.invalidateQueries({ queryKey: api.queryKeys.campaign(campaignId), exact: true });
        return;
      }
      qc.invalidateQueries({ queryKey: api.queryKeys.map(moduleId, mapName) });
      qc.invalidateQueries({ queryKey: api.queryKeys.module(moduleId), exact: true });
      qc.invalidateQueries({ queryKey: api.queryKeys.modules });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 400) setRenderError(parseError(e));
    },
  });

  // Cmd/Ctrl+S: triggered either from inside Monaco (it has its own
  // command binding) or from the document when focus is elsewhere.
  const onSave = useCallback(() => {
    if (!dirty || save.isPending) return;
    save.mutate();
  }, [dirty, save]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        onSave();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSave]);

  // Warn before unloading the tab (close / reload / external link) with unsaved
  // changes. This covers full-page unloads; in-app navigation is handled by the
  // router blocker below.
  useEffect(() => {
    if (!dirty) return;
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  // Confirm before leaving the editor via in-app navigation (breadcrumb, header
  // links, the browser Back button, …) while there are unsaved changes. Only
  // blocks an actual route change, not a same-page update.
  const shouldBlock = useCallback<BlockerFunction>(
    ({ currentLocation, nextLocation }) =>
      dirty && currentLocation.pathname !== nextLocation.pathname,
    [dirty],
  );
  const blocker = useBlocker(shouldBlock);
  const confirm = useConfirm();
  const asking = useRef(false);
  useEffect(() => {
    if (blocker.state !== "blocked" || asking.current) return;
    asking.current = true;
    void confirm({ title: t("editor.leaveUnsaved"), confirm: t("dialog.leave") }).then((leave) => {
      asking.current = false;
      if (leave) blocker.proceed();
      else blocker.reset();
    });
  }, [blocker, confirm, t]);

  function downloadSvg() {
    const svg = preview?.svg;
    if (!svg) return;
    const blob = new Blob([svg], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${map?.name ?? "map"}.svg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  if (loadError) {
    return (
      <div className={`editor-scope ${styles.page}`}>
        <p role="alert" className={styles.loadingState}>
          {t("editor.loadFailed", { error: loadError.message })}
        </p>
      </div>
    );
  }
  if (isLoading || !map) {
    return (
      <div className={`editor-scope ${styles.page}`}>
        <div className={styles.loadingState}>{t("editor.loading")}</div>
      </div>
    );
  }

  const editorPane = (
    <div className={phone && pane !== "code" ? `${styles.editorPane} ${styles.paneHidden}` : styles.editorPane}>
      <div className={styles.editorBox}>
        <MonacoEditor
          value={source}
          onChange={setSource}
          diagnostics={diagnostics}
          onSave={onSave}
          goto={goto}
          onCursor={setCursor}
          wordWrap={wordWrap}
        />
        <button
          type="button"
          className={styles.wrapToggle}
          data-active={wordWrap || undefined}
          aria-pressed={wordWrap}
          onClick={() => setWordWrap((w) => !w)}
          title={wordWrap ? t("editor.wrap.on") : t("editor.wrap.off")}
        >
          {t("editor.wrap")}
        </button>
      </div>
      <DiagnosticsPanel diagnostics={diagnostics} onJump={onJump} />
    </div>
  );

  const previewPane = (
    <div className={phone && pane !== "drawing" ? `${styles.previewPane} ${styles.paneHidden}` : styles.previewPane}>
      <DrawToolbar
        tool={tool}
        onTool={setTool}
        snap={snap}
        onSnap={setSnap}
        snapResolution={snapResolution}
        onSnapResolution={setSnapResolution}
        bgImage={bgImage}
        onBgImage={setBgImage}
        bgOpacity={bgOpacity}
        onBgOpacity={setBgOpacity}
        doorType={doorType}
        onDoorType={setDoorType}
        doorState={doorState}
        onDoorState={setDoorState}
        doorFacing={doorFacing}
        onDoorFacing={setDoorFacing}
        doorTrapped={doorTrapped}
        onDoorTrapped={setDoorTrapped}
        featureType={featureType}
        onFeatureType={setFeatureType}
        featureTypes={featureTypes}
        featureGroups={featureGroups}
        featureRotate={featureRotate}
        onFeatureRotate={setFeatureRotate}
        featureScale={featureScale}
        onFeatureScale={setFeatureScale}
        featureGlobal={featureGlobal}
        onFeatureGlobal={setFeatureGlobal}
        corridorOrganic={corridorOrganic}
        onCorridorOrganic={setCorridorOrganic}
        corridorStraight={corridorStraight}
        onCorridorStraight={setCorridorStraight}
        textContent={textContent}
        onTextContent={setTextContent}
        textSize={textSize}
        onTextSize={setTextSize}
        textDescription={textDescription}
        onTextDescription={setTextDescription}
        textGlobal={textGlobal}
        onTextGlobal={setTextGlobal}
        areaKind={areaKind}
        onAreaKind={setAreaKind}
        areaOrganic={areaOrganic}
        onAreaOrganic={setAreaOrganic}
        lineKind={lineKind}
        onLineKind={setLineKind}
        exitTargetMap={exitTargetMap}
        onExitTargetMap={setExitTargetMap}
        exitMapOptions={exitMapOptions}
        exitTargetX={exitTargetX}
        onExitTargetX={setExitTargetX}
        exitTargetY={exitTargetY}
        onExitTargetY={setExitTargetY}
        exitLabel={exitLabel}
        onExitLabel={setExitLabel}
        exitSecret={exitSecret}
        onExitSecret={setExitSecret}
        exitGlobal={exitGlobal}
        onExitGlobal={setExitGlobal}
        pathCheck={pathCheck}
        onPathCheck={setPathCheck}
        connectionsMode={connectionsMode}
        onConnectionsMode={(v) => {
          setConnectionsMode(v);
          if (!v) setSelectedNode(null);
        }}
        cellGrid={hasCellGrid(source)}
        onCellGrid={(v) => setSource((s) => setCellGrid(s, v))}
        onSort={() => setSource((s) => sortSource(s))}
        disabled={isLibrary}
      />
      <div className={styles.previewArea}>
        <SvgPreview
          svg={preview?.svg ?? null}
          error={renderError?.message ?? null}
          loading={previewLoading}
          tool={tool}
          snap={snap}
          snapResolution={snapResolution}
          bgImage={bgImage}
          bgOpacity={bgOpacity}
          doorType={doorType}
          doorState={doorState}
          doorFacing={doorFacing}
          doorTrapped={doorTrapped}
          featureType={featureType}
          featureRotate={featureRotate}
          featureScale={featureScale}
          featureGlobal={featureGlobal}
          corridorOrganic={corridorOrganic}
          corridorStraight={corridorStraight}
          textContent={textContent}
          textSize={textSize}
          textDescription={textDescription}
          textGlobal={textGlobal}
          areaKind={areaKind}
          areaOrganic={areaOrganic}
          lineKind={lineKind}
          exitTargetMap={exitTargetMap}
          exitTargetX={exitTargetX}
          exitTargetY={exitTargetY}
          exitLabel={exitLabel}
          exitSecret={exitSecret}
          exitGlobal={exitGlobal}
          pathCheck={pathCheck}
          connectivity={connectivity}
          highlightAt={cursor}
          onEmit={onEmit}
          onPick={onPick}
          notice={
            isLibrary
              ? t("editor.libraryNotice")
              : null
          }
        />
        {connectionsMode && selectedNode ? (
          <div className={styles.connPanel}>
            <div className={styles.connHeader}>
              <span className={styles.connTitle}>{selectedNode}</span>
              <button
                type="button"
                className={styles.connClose}
                onClick={() => setSelectedNode(null)}
                aria-label={t("editor.close")}
              >
                ×
              </button>
            </div>
            {(() => {
              const node = connectivity?.find((n) => n.id === selectedNode);
              if (!node) return <div className={styles.connEmpty}>…</div>;
              if (node.connections.length === 0)
                return (
                  <div className={styles.connEmpty}>{t("editor.noDoors")}</div>
                );
              return (
                <ul className={styles.connList}>
                  {node.connections.map((c, i) => (
                    <li key={i}>
                      <span className={styles.connArrow}>
                        {c.direction === "out"
                          ? "→"
                          : c.direction === "in"
                            ? "←"
                            : "↔"}
                      </span>
                      <span className={styles.connTo}>{c.to}</span>
                      <span className={styles.connMeta}>
                        {c.type}
                        {c.state && c.state !== "closed"
                          ? `, ${c.state}`
                          : ""}
                      </span>
                    </li>
                  ))}
                </ul>
              );
            })()}
          </div>
        ) : null}
      </div>
    </div>
  );

  return (
    <div className={`editor-scope ${styles.page}`}>
      <header className={styles.header}>
        {own ? (
          <Link to={`/campaigns/${encodeURIComponent(campaignId)}?tab=maps`} className={styles.crumb}>
            {campaign?.name ?? campaignId}
          </Link>
        ) : (
          <Link to={`/modules/${encodeURIComponent(moduleId)}`} className={styles.crumb}>
            {module?.title ?? moduleId}
          </Link>
        )}
        <span className={styles.crumbSep}>/</span>
        <span className={styles.mapName}>{map.name}</span>
        {dirty ? (
          <span className={styles.dirty} title={t("editor.unsaved")}>
            ●
          </span>
        ) : null}
        {save.error && !(save.error instanceof ApiError && save.error.status === 400) ? (
          <span role="alert" className={styles.saveError}>
            {t("editor.saveFailed", { error: save.error.message })}
          </span>
        ) : null}
        {own && <span className="tag">{t("ownMaps.tag")}</span>}
        <div className={styles.headerActions}>
          {!own && (
            <Button
              variant="ghost"
              disabled={dirty}
              onClick={() => navigate(`/maps/${encodeURIComponent(moduleId)}/${encodeURIComponent(mapName)}/print`)}
              title={dirty ? t("editor.print.saveFirst") : t("editor.print.open")}
            >
              {t("editor.print")}
            </Button>
          )}
          <Button
            variant="ghost"
            onClick={openSimplify}
            disabled={!source.trim()}
            title={t("editor.simplify.hint")}
          >
            {t("editor.simplify")}
          </Button>
          <Button
            variant="secondary"
            disabled={!preview?.svg}
            onClick={downloadSvg}
          >
            {t("editor.downloadSvg")}
          </Button>
          <Button onClick={onSave} disabled={!dirty || save.isPending}>
            {save.isPending ? t("editor.saving") : t("editor.save")}
          </Button>
        </div>
      </header>
      {!own && <ProvenanceNotice
        moduleId={moduleId}
        source={source}
        mapName={mapName}
        onShowPage={setPageShown}
        pageShown={pageShown}
        className={styles.notice}
      />}
      {phone ? (
        <div role="tablist" className={styles.paneTabs} aria-label={t("editor.panes")}>
          {(["code", "drawing"] as const).map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={pane === name}
              className={styles.paneTab}
              onClick={() => setPane(name)}
            >
              {t(`editor.pane.${name}`)}
            </button>
          ))}
        </div>
      ) : null}
      <div className={styles.body}>
        {phone ? (
          <div className={`${styles.workspace} ${styles.workspacePhone}`}>
            {editorPane}
            {previewPane}
          </div>
        ) : (
          <Split
            id="map-editor"
            className={styles.workspace}
            overflow="visible"
            start={{ size: 50, min: 240, children: editorPane }}
            end={{ size: 50, min: 280, children: previewPane }}
          />
        )}
        {bookPage ? (
          <aside className={styles.bookPage}>
            <img src={attachmentUrl(moduleId, bookPage)} alt={t("module.map.page")} />
          </aside>
        ) : null}
      </div>
      {simplifyOpen ? (
        <SimplifyDialog
          result={simplifyResult?.for === source ? simplifyResult.result : null}
          doorSpurs={simplifyDoorSpurs}
          loading={simplifyLoading}
          error={simplifyError}
          onDoorSpurs={(v) => {
            setSimplifyDoorSpurs(v);
            runSimplify(v);
          }}
          onApply={applySimplify}
          onClose={() => setSimplifyOpen(false)}
          onJump={(line) =>
            setGoto((g) => ({ line, column: 1, nonce: (g?.nonce ?? 0) + 1 }))
          }
        />
      ) : null}
    </div>
  );
}

/** A 400 from render or save: `{error, line, column}`, the source doesn't parse. */
function parseError(e: ApiError): { message: string; line?: number; column?: number } {
  const body = e.body as Partial<ParseErrorBody>;
  return {
    message: body.error ?? e.message,
    line: typeof body.line === "number" ? body.line : undefined,
    column: typeof body.column === "number" ? body.column : undefined,
  };
}
