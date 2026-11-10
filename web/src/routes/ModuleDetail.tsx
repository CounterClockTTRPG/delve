import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  ENTITY_KINDS,
  NeedsToken,
  createMap,
  createText,
  deleteMap,
  deleteModule,
  deleteText,
  exportModuleUrl,
  getModule,
  getModuleSource,
  listConversions,
  markModuleReady,
  putMap,
  queryKeys,
  setDefaultMap,
  type ConversionWarning,
  type EntityKind,
  type EntityRecord,
  type ModuleDetail as ModuleDetailShape,
  type ModuleMapEntry,
  type ModuleSource,
} from "../api";
import Banner from "../campaign/Banner";
import { useConfirm, usePrompt } from "../components/dialogs";
import ListAndEditor from "../desktop/ListAndEditor";
import PickList from "../desktop/PickList";
import type { MapRole } from "../editor/types";
import { useT } from "../i18n";
import AttachmentsPanel from "../module/AttachmentsPanel";
import AudienceBar, { ChooseAll, ChooseRow, entityRef, textRef, useChosen } from "../module/AudienceBar";
import { markSeen } from "../module/conversions";
import DetailsForm from "../module/DetailsForm";
import EntityForm from "../module/EntityForm";
import FixIts from "../module/FixIts";
import GenerateMap from "../module/GenerateMap";
import MakingQuestions from "../module/MakingQuestions";
import MapDrafts from "../module/MapDrafts";
import { ModuleLibraryBar } from "../modules/Library";
import NovelsSection, { useOwner } from "../novels/NovelsSection";
import { getModuleBanners, moduleBannerUrl, playKeys } from "../play/api";
import WorldMapsPanel from "../module/WorldMapsPanel";
import SketchNotice from "../module/SketchNotice";
import { slugify } from "../module/MarkdownRoundTrip";
import ModuleBannerPanel from "../module/ModuleBannerPanel";
import ModuleCategoryMenu from "../module/ModuleCategoryMenu";
import TextEditor, { type TextEditorHandle } from "../module/TextEditor";
import { revisionLine } from "./Modules";

const ROLES: MapRole[] = ["map", "library"];

const TABS = [
  "details",
  "text",
  "npcs",
  "encounters",
  "factions",
  "quests",
  "pregens",
  "attachments",
  "maps",
  "checks",
  "novels",
] as const;
type Tab = (typeof TABS)[number];

type UpdateSource = (change: (source: ModuleSource) => ModuleSource) => void;

/**
 * `/modules/:moduleId`: the module in tabs. The details first, where the page opens (the banner and the metadata);
 * the text (the word processor); the NPCs, encounters, factions and quests as forms; the attachments; the maps (add,
 * rename, delete, default, role), each with a link to its editor; the checks (its warnings, the conversion's doubts and
 * questions, the fix-it comments); and, for the owner alone, its novels. The head holds only the title, the category and the actions
 * (library, Export, Print), so the tabs come at once (DEL-183: the page opened on 170 doubts, the fix-it comments and
 * the banner's forms, with Export and Print below the fold). Every tab stays mounted, so a text keeps its unsaved
 * changes and its cursor while another tab is open, and "Insert in text" places an attachment where the cursor was.
 */
export default function ModuleDetail() {
  const { moduleId = "" } = useParams();
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  // Set by the .dscn import or the conversion that opened this page.
  const opener = location.state as { warnings?: (string | ConversionWarning)[]; from?: "conversion" } | null;
  // Without them (a reload), the newest finished conversion that made this module keeps its warnings in view.
  const conversions = useQuery({ queryKey: queryKeys.conversions, queryFn: listConversions, enabled: !opener?.warnings });
  const madeBy = conversions.data?.find((c) => c.module_id === moduleId && c.status === "done");
  const warnings: ConversionWarning[] =
    opener?.warnings?.map((w) => (typeof w === "string" ? { code: "", message: w, ref: "" } : w)) ?? madeBy?.warnings ?? [];
  const fromConversion = opener?.warnings ? opener.from === "conversion" : madeBy !== undefined;
  // The module is opened: the conversion that made it is no longer a row on Modules.
  useEffect(() => markSeen(moduleId), [moduleId]);
  const module = useQuery({ queryKey: queryKeys.module(moduleId), queryFn: () => getModule(moduleId) });
  const source = useQuery({ queryKey: queryKeys.moduleSource(moduleId), queryFn: () => getModuleSource(moduleId) });
  const editor = useRef<TextEditorHandle>(null);
  const [newMap, setNewMap] = useState("");
  const [newRole, setNewRole] = useState<MapRole>("map");
  const [params, setParams] = useSearchParams();
  // The novels are the owner's alone: a seat has no such tab.
  const tabs: readonly Tab[] = useOwner() ? TABS : TABS.filter((name) => name !== "novels");
  const tab: Tab = (tabs as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "details";

  const changed = () => {
    client.invalidateQueries({ queryKey: queryKeys.module(moduleId) });
    client.invalidateQueries({ queryKey: queryKeys.modules });
  };
  // Every change to the module goes through this one mutation, so one place shows its failure.
  const change = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: changed });
  const ready = useMutation({
    mutationFn: () => markModuleReady(moduleId),
    onSuccess: (saved) => {
      client.setQueryData(queryKeys.module(moduleId), saved);
      client.invalidateQueries({ queryKey: queryKeys.modules });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteModule(moduleId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.modules });
      navigate("/modules");
    },
  });

  if (module.error && !(module.error instanceof NeedsToken)) {
    return (
      <section className="page">
        <p>
          <Link to="/modules">{t("module.back")}</Link>
        </p>
        <p role="alert" className="notice error">
          {t("module.loadFailed", { error: module.error.message })}
        </p>
      </section>
    );
  }
  if (!module.data) {
    return (
      <section className="page">
        <p className="placeholder">{t("module.loading")}</p>
      </section>
    );
  }
  const m = module.data;
  const updateSource: UpdateSource = (edit) =>
    client.setQueryData<ModuleSource>(queryKeys.moduleSource(moduleId), (old) => (old ? edit(old) : old));
  const open = (name: Tab) => setParams(name === "details" ? {} : { tab: name }, { replace: true });
  // The parts that live in the module's source wait for it.
  const withSource = (render: (s: ModuleSource) => ReactNode) =>
    source.data ? (
      render(source.data)
    ) : source.error && !(source.error instanceof NeedsToken) ? (
      <p role="alert" className="notice error">
        {t("module.sourceFailed", { error: source.error.message })}
      </p>
    ) : (
      <p className="placeholder">{t("module.sourceLoading")}</p>
    );

  function add(e: FormEvent) {
    e.preventDefault();
    const name = newMap.trim();
    if (!name) return;
    change.mutate(() => createMap(moduleId, name, newRole), { onSuccess: () => setNewMap("") });
  }

  const failed = change.error ?? ready.error ?? remove.error;
  const failure =
    failed && !(failed instanceof NeedsToken)
      ? failed instanceof ApiError && failed.status === 409 && remove.error === failed
        ? t("module.inUse")
        : t("module.changeFailed", { error: failed.message })
      : null;

  return (
    <section className="page">
      <p>
        <Link to="/modules">{t("module.back")}</Link>
      </p>
      <h1>{m.title}</h1>
      <p className="row-meta">{revisionLine(t, m.head_revision)}</p>
      <div className="module-head-actions">
        <ModuleCategoryMenu module={m} />
        <ModuleLibraryBar module={m} />
        <a className="button-like" href={exportModuleUrl(moduleId)} download>
          {t("module.export")}
        </a>
        <Link className="button-like" to={`/modules/${encodeURIComponent(moduleId)}/print`}>
          {t("module.print")}
        </Link>
      </div>

      {m.draft && (
        <div className="notice draft-notice" role="note">
          <p>
            <span className="tag">{t("module.draft")}</span> {t("module.draftHint")}
          </p>
          <button type="button" className="primary" disabled={ready.isPending} onClick={() => ready.mutate()}>
            {t("module.markReady")}
          </button>
        </div>
      )}

      {failure && (
        <p role="alert" className="notice error">
          {failure}
        </p>
      )}

      <div role="tablist" className="view-tabs module-tabs" aria-label={t("module.tabs")}>
        {tabs.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            id={`module-tab-${name}`}
            aria-selected={tab === name}
            aria-controls={`module-panel-${name}`}
            className="view-tab"
            onClick={() => open(name)}
          >
            {t(`module.tab.${name}`)}
          </button>
        ))}
      </div>

      <TabPanel name="text" active={tab}>
        {withSource((s) => (
          <TextsTab module={m} source={s} update={updateSource} editor={editor} onChecks={() => open("checks")} />
        ))}
      </TabPanel>

      {ENTITY_KINDS.map((kind) => (
        <TabPanel key={kind} name={kind} active={tab}>
          {withSource((s) => (
            <EntitiesTab module={m} kind={kind} source={s} update={updateSource} />
          ))}
        </TabPanel>
      ))}

      <TabPanel name="attachments" active={tab}>
        {withSource((s) => (
          <AttachmentsPanel
            moduleId={moduleId}
            attachments={s.attachments}
            texts={s.texts}
            canInsert={s.texts.length > 0}
            onChange={(attachments) => {
              updateSource((old) => ({ ...old, attachments }));
              // A deleted attachment leaves warnings in the texts that show it.
              client.invalidateQueries({ queryKey: queryKeys.moduleSource(moduleId), exact: true });
            }}
            onInsert={(attachment) => {
              open("text");
              editor.current?.insertAttachment(attachment);
            }}
          />
        ))}
      </TabPanel>

      <TabPanel name="maps" active={tab}>
        <h2>{t("module.maps")}</h2>
        {m.maps.length === 0 ? (
          <p className="placeholder">{t("module.noMaps")}</p>
        ) : (
          <ul className="rows">
            {m.maps.map((map) => (
              <MapRow
                key={map.name}
                map={map}
                moduleId={moduleId}
                busy={change.isPending}
                onChange={(run) => change.mutate(run)}
              />
            ))}
          </ul>
        )}

        <form className="inline-form" onSubmit={add}>
          <div className="field">
            <label htmlFor="new-map-name">{t("module.map.newName")}</label>
            <input id="new-map-name" value={newMap} onChange={(e) => setNewMap(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="new-map-role">{t("module.map.role")}</label>
            <select id="new-map-role" value={newRole} onChange={(e) => setNewRole(e.target.value as MapRole)}>
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {t(`module.role.${role}`)}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="primary" disabled={change.isPending}>
            {t("module.map.add")}
          </button>
        </form>
        <div className="actions">
          <GenerateMap moduleId={moduleId} />
        </div>
        <MapDrafts moduleId={moduleId} />
        <WorldMapsPanel
          moduleId={moduleId}
          setting={typeof m.metadata.setting === "string" ? m.metadata.setting : undefined}
        />
      </TabPanel>

      <TabPanel name="checks" active={tab}>
        <ModuleWarnings
          moduleId={moduleId}
          maps={m.maps.map((map) => map.name)}
          heading={
            warnings.length > 0
              ? t(fromConversion ? "module.conversionWarnings" : "module.importWarnings")
              : t("module.sourceWarnings")
          }
          warnings={[...warnings, ...(source.data?.warnings ?? [])]}
        />
        <MakingQuestions moduleId={moduleId} />
        <FixIts moduleId={moduleId} maps={m.maps} source={source.data} />
      </TabPanel>

      <TabPanel name="details" active={tab}>
        <ModuleBannerPanel module={m} attachments={source.data?.attachments ?? []} />
        <CampaignBanners moduleId={moduleId} />
        {withSource((s) => (
          <DetailsForm
            module={m}
            attachments={s.attachments}
            onSaved={(saved) => {
              client.setQueryData(queryKeys.module(moduleId), saved);
              client.invalidateQueries({ queryKey: queryKeys.modules });
            }}
          />
        ))}
      </TabPanel>

      {tabs.includes("novels") && (
        <TabPanel name="novels" active={tab}>
          <NovelsSection source={{ kind: "module", id: moduleId }} />
        </TabPanel>
      )}

      <div className="actions">
        <button
          type="button"
          className="danger"
          disabled={remove.isPending}
          onClick={async () =>
            (await confirm({ title: t("module.deleteConfirm", { title: m.title }), confirm: t("dialog.delete"), danger: true })) &&
            remove.mutate()
          }
        >
          {t("module.delete")}
        </button>
      </div>
    </section>
  );
}

/**
 * The module's warnings, its conversion's or import's and its source's own, as one collapsed line that counts them
 * and their distinct codes ("53 warnings, 4 kinds"): grouped by code with a count ("13 × Pages too large to render
 * whole"), each linked to its text, attachment, map or room where it can be.
 */
/** The module's campaigns that have a banner, as thumbnails that open their campaign; nothing while none has one. */
function CampaignBanners({ moduleId }: { moduleId: string }) {
  const t = useT();
  const banners = useQuery({ queryKey: playKeys.moduleBanners(moduleId), queryFn: () => getModuleBanners(moduleId) });
  if (!banners.data?.length) return null;
  return (
    <>
      <h2>{t("module.campaigns")}</h2>
      <ul className="banner-thumbs">
        {banners.data.map((b) => (
          <li key={b.campaign_id}>
            <Link to={`/campaigns/${encodeURIComponent(b.campaign_id)}`}>
              <Banner
                src={moduleBannerUrl(moduleId, b.campaign_id, b.image_id, "card")}
                alt={t("banner.alt", { name: b.name })}
                variant="thumb"
              />
              <span className="banner-name">{b.name}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

function ModuleWarnings({
  moduleId,
  maps,
  heading,
  warnings,
}: {
  moduleId: string;
  maps: string[];
  heading: string;
  warnings: ConversionWarning[];
}) {
  const t = useT();
  const groups = new Map<string, ConversionWarning[]>();
  const seen = new Set<string>();
  for (const w of warnings) {
    const id = `${w.code}\u0000${w.ref}\u0000${w.message}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const key = w.code || w.message;
    groups.set(key, [...(groups.get(key) ?? []), w]);
  }
  if (seen.size === 0) return null;
  const label = (code: string) => {
    const key = `module.warningCode.${code}`;
    const text = t(key);
    return text === key ? code : text;
  };
  const item = (w: ConversionWarning) => {
    const to = warningTarget(moduleId, w.ref, maps);
    return to ? <Link to={to}>{w.message}</Link> : w.message;
  };

  return (
    <details className="notice module-warnings">
      <summary>
        <span>{heading}</span>{" "}
        <span className="row-meta">
          {seen.size === 1 ? t("module.warningCount.one") : t("module.warningCount", { count: String(seen.size) })}
          {seen.size > 1 &&
            `, ${groups.size === 1 ? t("module.warningKinds.one") : t("module.warningKinds", { count: String(groups.size) })}`}
        </span>
      </summary>
      <ul>
        {[...groups.entries()].map(([key, items]) =>
          items.length === 1 ? (
            <li key={key}>{item(items[0])}</li>
          ) : (
            <li key={key}>
              <details>
                <summary>
                  <span>{t("module.warningGroup", { count: String(items.length) })}</span> {label(items[0].code)}
                </summary>
                <ul>
                  {items.map((w) => (
                    <li key={`${w.ref}\u0000${w.message}`}>{item(w)}</li>
                  ))}
                </ul>
              </details>
            </li>
          ),
        )}
      </ul>
    </details>
  );
}

/**
 * Where a warning's `ref` leads: a text or an attachment on this page, an entity's tab (`npc:<id>`, or the
 * conversion's `npcs:<id>`), or a map's editor (`map:<name>`, `map:<name>#<room>`) when the module has that map.
 * None for a page.
 */
function warningTarget(moduleId: string, ref: string, maps: string[]): string | null {
  const [kind, rest = ""] = ref.split(/:(.*)/s, 2);
  const [id] = rest.split("#", 1);
  if (!id) return null;
  const page = `/modules/${encodeURIComponent(moduleId)}`;
  if (kind === "text") return `${page}?tab=text&text=${encodeURIComponent(id)}`;
  if (kind === "asset") return `${page}?tab=attachments`;
  const entities = (ENTITY_KINDS as readonly string[]).find((k) => k === kind || k === `${kind}s`);
  if (entities) return `${page}?tab=${entities}`;
  if (kind === "map" && maps.includes(id)) return `/maps/${encodeURIComponent(moduleId)}/${encodeURIComponent(id)}`;
  return null;
}

function TabPanel({ name, active, children }: { name: Tab; active: Tab; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`module-panel-${name}`} aria-labelledby={`module-tab-${name}`} hidden={name !== active}>
      {children}
    </div>
  );
}

/** The module's texts: a list beside the editor of the one that is open. */
function TextsTab({
  module,
  source: s,
  update,
  editor,
  onChecks,
}: {
  module: ModuleDetailShape;
  source: ModuleSource;
  update: UpdateSource;
  editor: RefObject<TextEditorHandle>;
  /** Opens the Checks tab, where the rooms without text are listed with the other warnings. */
  onChecks: () => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const prompt = usePrompt();
  const client = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [params, setParams] = useSearchParams();
  const wanted = params.get("text");
  const chosen = useChosen(s.texts.map((text) => textRef(text.id)));

  const create = useMutation({
    mutationFn: (title: string) => {
      const taken = new Set(s.texts.map((text) => text.id));
      const base = slugify(title);
      let id = base;
      for (let n = 2; taken.has(id); n++) id = `${base}-${n}`;
      return createText(module.id, { id, title });
    },
    onSuccess: (text) => {
      update((s) => ({ ...s, texts: [...s.texts, text] }));
      setSelected(text.id);
    },
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteText(module.id, id).then(() => getModuleSource(module.id)),
    onSuccess: (fresh) => {
      client.setQueryData(queryKeys.moduleSource(module.id), fresh);
      setSelected(null);
      setDirty(false);
    },
  });

  const open = s.texts.find((text) => text.id === selected) ?? s.texts[0];
  const rooms = s.warnings.filter((w) => w.code === "room-without-text");
  const failed = create.error ?? remove.error;

  async function choose(id: string) {
    if (id === open?.id) return;
    if (dirty && !(await confirm({ title: t("module.text.switchUnsaved"), confirm: t("dialog.openOther") }))) return;
    setDirty(false);
    setSelected(id);
  }

  // A warning's link opens its text (`?text=`), once: the parameter goes, so the link works again.
  useEffect(() => {
    if (!wanted) return;
    setParams(
      (now) => {
        now.delete("text");
        return now;
      },
      { replace: true },
    );
    if (s.texts.some((text) => text.id === wanted)) void choose(wanted);
  }, [wanted]); // eslint-disable-line react-hooks/exhaustive-deps

  async function add() {
    const title = (await prompt({ title: t("module.text.new"), label: t("module.text.newPrompt"), confirm: t("dialog.make") }))?.trim();
    if (title) create.mutate(title);
  }

  return (
    <ListAndEditor id="module-texts" className="module-texts">
      <aside className="text-list">
        <h2>{t("module.texts")}</h2>
        <ChooseAll chosen={chosen} count={s.texts.length} />
        {s.texts.length === 0 ? (
          <p className="placeholder">{t("module.noTexts")}</p>
        ) : (
          <PickList
            items={s.texts}
            keyOf={(text) => text.id}
            current={s.texts.findIndex((text) => text.id === open?.id)}
            render={(text) => (
              <ChooseRow chosen={chosen} itemRef={textRef(text.id)} name={text.title}>
                <button type="button" className="text-pick" aria-current={text.id === open?.id} onClick={() => choose(text.id)}>
                  <span>{text.title}</span>
                  {text.audience === "gm" && <span className="tag">{t("module.text.dmOnly")}</span>}
                  {text.map && !module.maps.some((map) => map.name === text.map) && (
                    <span className="tag">{t("module.noSuchMap")}</span>
                  )}
                </button>
              </ChooseRow>
            )}
          />
        )}
        <AudienceBar selected={chosen.refs} onDone={chosen.clear} moduleId={module.id} />
        <div className="actions">
          <button type="button" disabled={create.isPending} onClick={add}>
            {t("module.text.new")}
          </button>
          {open && (
            <button
              type="button"
              className="danger"
              disabled={remove.isPending}
              onClick={async () =>
                (await confirm({ title: t("module.text.deleteConfirm", { title: open.title }), confirm: t("dialog.delete"), danger: true })) &&
                remove.mutate(open.id)
              }
            >
              {t("module.text.delete")}
            </button>
          )}
        </div>
        {failed && !(failed instanceof NeedsToken) && (
          <p role="alert" className="notice error">
            {t("module.changeFailed", { error: failed.message })}
          </p>
        )}
        {rooms.length > 0 && (
          <p className="notice" role="note">
            {t("module.roomsWithoutTextCount", { n: String(rooms.length) })}{" "}
            <button type="button" className="link-button" onClick={onChecks}>
              {t("module.seeChecks")}
            </button>
          </p>
        )}
      </aside>
      {open && (
        <TextEditor
          ref={editor}
          key={open.id}
          moduleId={module.id}
          text={open}
          links={s.links}
          attachments={s.attachments}
          warnings={s.warnings}
          entities={s.entities}
          maps={module.maps.filter((map) => map.role === "map").map((map) => map.name)}
          onDirtyChange={setDirty}
          onSaved={(saved) =>
            update((old) => ({
              ...old,
              texts: old.texts.map((text) => (text.id === saved.text.id ? saved.text : text)),
              links: saved.links,
              warnings: saved.warnings,
              headings: saved.headings,
            }))
          }
        />
      )}
    </ListAndEditor>
  );
}

/** One kind of entity: a list beside the form of the one that is open, or of a new one. */
function EntitiesTab({
  module,
  kind,
  source: s,
  update,
}: {
  module: ModuleDetailShape;
  kind: EntityKind;
  source: ModuleSource;
  update: UpdateSource;
}) {
  const t = useT();
  const client = useQueryClient();
  const records = s.entities[kind] ?? [];
  // null: the first one, if any; "": a new one.
  const [selected, setSelected] = useState<string | null>(null);
  const open = selected === "" ? null : (records.find((r) => r.id === selected) ?? (selected === null ? records[0] : undefined));
  const chosen = useChosen(records.map((record) => entityRef(kind, record.id)));

  function saved(record: EntityRecord, warnings: ModuleSource["warnings"]) {
    update((old) => {
      const list = old.entities[kind] ?? [];
      const next = list.some((r) => r.id === record.id) ? list.map((r) => (r.id === record.id ? record : r)) : [...list, record];
      return { ...old, entities: { ...old.entities, [kind]: next }, warnings };
    });
    setSelected(record.id);
  }

  return (
    <ListAndEditor id="module-entities" className="module-entities">
      <aside className="text-list">
        <h2>{t(`module.tab.${kind}`)}</h2>
        <ChooseAll chosen={chosen} count={records.length} />
        {records.length === 0 ? (
          <p className="placeholder">{t(`module.entities.none.${kind}`)}</p>
        ) : (
          <PickList
            items={records}
            keyOf={(record) => record.id}
            current={records.findIndex((record) => record.id === open?.id)}
            render={(record) => (
              <ChooseRow chosen={chosen} itemRef={entityRef(kind, record.id)} name={record.name}>
                <button type="button" className="text-pick" aria-current={record.id === open?.id} onClick={() => setSelected(record.id)}>
                  <span>{record.name}</span>
                  {record.audience !== "player" && <span className="tag">{t("module.text.dmOnly")}</span>}
                </button>
              </ChooseRow>
            )}
          />
        )}
        <AudienceBar selected={chosen.refs} onDone={chosen.clear} moduleId={module.id} />
        <div className="actions">
          <button type="button" onClick={() => setSelected("")}>
            {t(`module.entities.new.${kind}`)}
          </button>
        </div>
      </aside>
      <EntityForm
        key={open?.id ?? "new"}
        moduleId={module.id}
        kind={kind}
        record={open ?? null}
        source={s}
        maps={module.maps.filter((map) => map.role === "map").map((map) => map.name)}
        onSaved={saved}
        onDeleted={() => {
          setSelected(null);
          client.invalidateQueries({ queryKey: queryKeys.moduleSource(module.id), exact: true });
        }}
      />
    </ListAndEditor>
  );
}

function MapRow({
  map,
  moduleId,
  busy,
  onChange,
}: {
  map: ModuleMapEntry;
  moduleId: string;
  busy: boolean;
  onChange: (run: () => Promise<unknown>) => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const [name, setName] = useState(map.name);
  const id = `map-${map.name.replace(/\W/g, "-")}`;
  const editor = `/maps/${encodeURIComponent(moduleId)}/${encodeURIComponent(map.name)}`;

  return (
    <li className="row map-row">
      <Link to={editor} className="row-title">
        {map.name}
      </Link>
      {map.is_default ? (
        <span className="tag">{t("module.map.default")}</span>
      ) : (
        <button type="button" disabled={busy} onClick={() => onChange(() => setDefaultMap(moduleId, map.name))}>
          {t("module.map.makeDefault")}
        </button>
      )}
      <select
        aria-label={t("module.map.roleOf", { name: map.name })}
        value={map.role}
        disabled={busy}
        onChange={(e) => onChange(() => putMap(moduleId, map.name, { role: e.target.value as MapRole }))}
      >
        {ROLES.map((role) => (
          <option key={role} value={role}>
            {t(`module.role.${role}`)}
          </option>
        ))}
      </select>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          const next = name.trim();
          if (next && next !== map.name) onChange(() => putMap(moduleId, map.name, { new_name: next }));
        }}
      >
        <input id={`${id}-name`} aria-label={t("module.map.nameOf", { name: map.name })} value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" disabled={busy || name.trim() === map.name || !name.trim()}>
          {t("module.map.rename")}
        </button>
      </form>
      <button
        type="button"
        className="danger"
        disabled={busy}
        onClick={async () =>
          (await confirm({ title: t("module.map.deleteConfirm", { name: map.name }), confirm: t("dialog.delete"), danger: true })) &&
          onChange(() => deleteMap(moduleId, map.name))
        }
      >
        {t("module.map.delete")}
      </button>
      <SketchNotice moduleId={moduleId} source={map.source} mapName={map.name} />
    </li>
  );
}
