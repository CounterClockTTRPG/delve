import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  CAMPAIGN_STATUSES,
  EventsContext,
  NeedsToken,
  getCampaignHouseRules,
  putCampaignHouseRules,
  type CampaignDetail as CampaignDetailShape,
  type CampaignHouseRules,
  type CampaignStatus,
  deleteCampaign,
  deleteCharacter,
  getCampaign,
  getDmCosts,
  getMapState,
  getWorlds,
  listDmCharacters,
  patchCampaign,
  queryKeys,
  renameCharacter,
  upgradeCampaign,
  type DmCostRow,
  type TableCharacter,
} from "../api";
import { boardKeys, getBoard, zoneOfCampaign } from "../board/api";
import Banner from "../campaign/Banner";
import CarryForm from "../campaign/CarryForm";
import CharacterSheet from "../campaign/CharacterSheet";
import { usePages } from "../components/Pager";
import Factions from "../campaign/Factions";
import HistorySection from "../campaign/HistorySection";
import HouseRulePicker from "../campaign/HouseRulePicker";
import MapStatePanel from "../campaign/MapStatePanel";
import Possessions from "../campaign/Possessions";
import Quests from "../campaign/Quests";
import TableListing from "../campaign/TableListing";
import TableSchedule from "../campaign/TableSchedule";
import TableSettings, { DepartureButtons } from "../campaign/TableSettings";
import OwnMaps from "../campaign/OwnMaps";
import WorldMaps from "../campaign/WorldMaps";
import Portrait from "../components/Portrait";
import { useConfirm } from "../components/dialogs";
import { PORTRAIT_STYLES, PortraitStyleProvider, SAMPLE_PORTRAIT } from "../components/portraitStyle";
import { useLanguage, useT } from "../i18n";
import { queuedLine } from "../components/waiting";
import NovelsSection, { useOwner } from "../novels/NovelsSection";
import { bannerUrl, getPlaySettings, getPlayState, getSeats, paintBannerAgain, playKeys, putPortraitStyle, type CampaignBanner } from "../play/api";
import PersonLink from "../profile/PersonLink";

const TABS = ["overview", "party", "maps", "world", "log", "novels"] as const;
type Tab = (typeof TABS)[number];

/** One tab's sections, rendered only while it is open, so a closed tab asks the server for nothing. */
function TabPanel({ name, active, children }: { name: Tab; active: Tab; children: ReactNode }) {
  if (name !== active) return null;
  return (
    <div role="tabpanel" id={`campaign-panel-${name}`} aria-labelledby={`campaign-tab-${name}`}>
      {children}
    </div>
  );
}

/** `/campaigns/:id`, the organiser's, in tabs kept in `?tab=` (Overview when none; `?map=` opens Maps): Overview has the
 * module and revision it plays, its status, its banner with Paint again, its History when its party was carried on
 * (or on from it), its table settings (voice, initiative) and its house rules; Party its characters, each PC with Leave
 * the party or Return, with their whole sheets (an NPC's story too) and its portrait style; Maps a map-state panel per map and the world maps; World
 * the factions and clocks, the quests and the possessions; DM log the log with its cost; and, for the owner alone,
 * Novels. Carry the party on (`?carry` opens it, as the campaigns list's row menu does) takes the party into a new
 * campaign. Beside the module, the Board link to the campaign's zone, once it has one; Delete says that zone stays. */
export default function CampaignDetail() {
  const { id = "" } = useParams();
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const navigate = useNavigate();
  const campaign = useQuery({ queryKey: queryKeys.campaign(id), queryFn: () => getCampaign(id) });
  const characters = useQuery({ queryKey: queryKeys.dmCharacters(id), queryFn: () => listDmCharacters(id) });
  const worlds = useQuery({ queryKey: queryKeys.worlds, queryFn: getWorlds });
  const tableZone = zoneOfCampaign(useQuery({ queryKey: boardKeys.all, queryFn: getBoard }).data, id);
  // `?map=` opens that map's state (the Maps page's DM view links).
  const [params, setParams] = useSearchParams();
  const [map, setMap] = useState<string | null>(() => params.get("map"));
  // The novels are the owner's alone: a seat has no such tab.
  const tabs: readonly Tab[] = useOwner() ? TABS : TABS.filter((name) => name !== "novels");
  const asked = params.get("tab") ?? (params.has("map") ? "maps" : "");
  const tab: Tab = (tabs as readonly string[]).includes(asked) ? (asked as Tab) : "overview";
  const open = (name: Tab) => setParams(name === "overview" ? {} : { tab: name }, { replace: true });
  const [carrying, setCarrying] = useState(() => params.has("carry"));
  const maps = campaign.data?.maps ?? [];
  const shown = map && maps.includes(map) ? map : maps[0];
  // The map state tool waits until play has put someone on one of the campaign's maps, so it can still move the party
  // to another (the panel reads the same queries). Asked for on the Maps tab only, as a closed tab asks for nothing.
  const mapStates = useQueries({
    queries: maps.map((name) => ({
      queryKey: [...queryKeys.mapState(id, name), "state"],
      queryFn: () => getMapState(id, name),
      enabled: tab === "maps",
    })),
  });
  const placed = mapStates.some((state) => Object.values(state.data?.characters ?? {}).some((where) => where.location));
  const waits = mapStates.length > 0 && mapStates.every((state) => state.isSuccess) && !placed;
  const mapStateError = mapStates[shown === undefined ? -1 : maps.indexOf(shown)]?.error;

  // A character change touches every map state (a removed character leaves them all).
  const refresh = () => client.invalidateQueries({ queryKey: queryKeys.campaign(id) });
  const change = useMutation({ mutationFn: (run: () => Promise<unknown>) => run(), onSuccess: refresh });
  const upgrade = useMutation({
    mutationFn: () => upgradeCampaign(id),
    onSuccess: () => {
      refresh();
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
    },
  });
  const status = useMutation({
    mutationFn: (next: CampaignStatus) => patchCampaign(id, { status: next }),
    onSuccess: () => {
      refresh();
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteCampaign(id),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
      navigate("/campaigns");
    },
  });

  const loadError = [campaign.error, characters.error].find((e) => e && !(e instanceof NeedsToken));
  if (loadError) {
    return (
      <section className="page">
        <p>
          <Link to="/campaigns">{t("campaign.back")}</Link>
        </p>
        <p role="alert" className="notice error">
          {t("campaign.loadFailed", { error: loadError.message })}
        </p>
      </section>
    );
  }
  if (!campaign.data || !characters.data) {
    return (
      <section className="page">
        <p className="placeholder">{t("campaign.loading")}</p>
      </section>
    );
  }
  const c = campaign.data;
  const titleOf = (list: { id: string; title: string }[] | undefined, worldId: string) =>
    list?.find((w) => w.id === worldId)?.title ?? worldId;

  const failed = [change.error, upgrade.error, status.error, remove.error].find((e) => e && !(e instanceof NeedsToken));

  return (
    <PortraitStyleProvider campaignId={id}>
      <section className="page campaign">
        <p>
          <Link to="/campaigns">{t("campaign.back")}</Link>
        </p>
        <h1>{c.name}</h1>
        <p className="lede">
          {t("campaign.plays", { module: c.module_title, revision: String(c.revision) })}{" "}
          <Link to={`/modules/${encodeURIComponent(c.module_id)}`}>{t("campaign.openModule")}</Link>
          {tableZone && (
            <>
              {" · "}
              <Link to={`/board/${encodeURIComponent(tableZone.id)}`}>{t("play.board")}</Link>
            </>
          )}
        </p>
        <p className="lede">
          {t("campaign.world", {
            ruleset: titleOf(worlds.data?.rulesets, c.ruleset),
            setting: c.setting ? titleOf(worlds.data?.settings, c.setting) : t("campaign.noSetting"),
          })}
        </p>
        <div className="field campaign-status">
          <label htmlFor="campaign-status">{t("campaign.status")}</label>
          <select
            id="campaign-status"
            value={c.status}
            disabled={status.isPending}
            onChange={(e) => status.mutate(e.target.value as CampaignStatus)}
          >
            {CAMPAIGN_STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`campaigns.status.${s}`)}
              </option>
            ))}
          </select>
        </div>
        {c.upgrade_available && (
          <div className="notice" role="note">
            <p>{t("campaign.upgradeAvailable")}</p>
            <button type="button" className="primary" disabled={upgrade.isPending} onClick={() => upgrade.mutate()}>
              {t("campaign.upgrade")}
            </button>
          </div>
        )}
        {failed && (
          <p role="alert" className="notice error">
            {t("campaign.changeFailed", { error: failed.message })}
          </p>
        )}

        <div role="tablist" className="view-tabs campaign-tabs" data-tour="campaign-tabs" aria-label={t("campaign.tabs")}>
          {tabs.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              id={`campaign-tab-${name}`}
              aria-selected={tab === name}
              aria-controls={`campaign-panel-${name}`}
              className="view-tab"
              onClick={() => open(name)}
            >
              {t(`campaign.tab.${name}`)}
            </button>
          ))}
        </div>

        <TabPanel name="overview" active={tab}>
          {characters.data.length === 0 && (
            <p>
              <Link className="button-like primary" to={`/play/${encodeURIComponent(id)}`} aria-describedby="first-step-how">
                {t("campaign.firstStep")}
              </Link>{" "}
              <span id="first-step-how" className="hint">
                {t("campaign.firstStepHow")}
              </span>
            </p>
          )}
          {c.banner && (
            <>
              <h2>{t("banner.title")}</h2>
              <BannerSection campaign={c} banner={c.banner} />
            </>
          )}

          <HistorySection campaign={c} />

          <h2 data-tour="table-settings">{t("tableSettings.title")}</h2>
          <TableSettings campaign={c} />

          <h2 data-tour="listing">{t("listing.title")}</h2>
          <p className="lede">{t("listing.intro")}</p>
          <TableListing campaign={c} />

          <h2 data-tour="schedule">{t("schedule.title")}</h2>
          <p className="lede">{t("schedule.intro")}</p>
          <TableSchedule campaign={c} />

          <h2 data-tour="house-rules">{t("campaign.houseRules")}</h2>
          <p className="lede">{t("campaign.houseRulesIntro")}</p>
          <CampaignHouseRulesEditor campaignId={id} />
        </TabPanel>

        <TabPanel name="party" active={tab}>
          <Seats campaignId={id} />

          <h2>{t("campaign.characters")}</h2>
          {characters.data.length === 0 ? (
            <p className="placeholder">{t("campaign.noCharacters")}</p>
          ) : (
            <ul className="rows">
              {characters.data.map((ch) => (
                <CharacterRow key={ch.id} campaignId={id} character={ch} busy={change.isPending} onChange={(run) => change.mutate(run)} />
              ))}
            </ul>
          )}
          <p className="hint">
            {t("campaign.madeInPlay")} <Link to={`/play/${encodeURIComponent(id)}`}>{t("campaign.toPlay")}</Link>
          </p>

          {characters.data.length > 0 && (
            <>
              <h2>{t("campaign.sheets")}</h2>
              <div className="sheets">
                {characters.data.map((ch) => (
                  <CharacterSheet key={ch.id} character={ch} organiser mayRepaint />
                ))}
              </div>
            </>
          )}

          <h2>{t("portraits.title")}</h2>
          <p className="lede">{t("portraits.intro")}</p>
          <PortraitStyleEditor campaignId={id} />
        </TabPanel>

        <TabPanel name="maps" active={tab}>
          <h2>{t("campaign.mapState")}</h2>
          <p className="lede">{t("campaign.mapStateIntro")}</p>
          {c.maps.length === 0 ? (
            <p className="placeholder">
              {t("campaign.noMaps")}{" "}
              <Link to={`/modules/${encodeURIComponent(c.module_id)}?tab=maps`}>{t("campaign.generateMap")}</Link>
            </p>
          ) : (
            <>
              {c.maps.length > 1 && (
                <div className="field map-picker">
                  <label htmlFor="campaign-map">{t("campaign.map")}</label>
                  <select id="campaign-map" value={shown} onChange={(e) => setMap(e.target.value)}>
                    {c.maps.map((m) => (
                      <option key={m} value={m}>
                        {c.own_maps?.includes(m) ? t("ownMaps.option", { name: m }) : m}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {mapStateError && !(mapStateError instanceof NeedsToken) ? (
                <p role="alert" className="notice error">
                  {t("campaign.mapStateFailed", { error: mapStateError.message })}
                </p>
              ) : placed ? (
                <details className="map-state-fix" open={params.has("map")}>
                  <summary>{t("campaign.mapStateFix")}</summary>
                  <MapStatePanel key={shown} campaignId={id} mapName={shown} characters={characters.data} />
                </details>
              ) : (
                waits && <p className="placeholder">{t("campaign.mapStateWaits")}</p>
              )}
            </>
          )}

          <h2>{t("campaign.ownMaps")}</h2>
          <OwnMaps campaignId={id} />

          <h2>{t("campaign.worldMaps")}</h2>
          <p className="lede">{t("campaign.worldMapsIntro")}</p>
          <WorldMaps campaignId={id} />
        </TabPanel>

        <TabPanel name="world" active={tab}>
          <h2>{t("campaign.factions")}</h2>
          <Factions campaignId={id} />

          <h2>{t("campaign.quests")}</h2>
          <Quests campaignId={id} />

          <h2>{t("campaign.possessions")}</h2>
          <Possessions
            campaignId={id}
            owners={characters.data.filter((ch) => ch.kind === "pc").map((ch) => ({ id: ch.id, name: ch.name }))}
          />
        </TabPanel>

        <TabPanel name="log" active={tab}>
          <h2 id="campaign-story-log">{t("log.title")}</h2>
          <p className="lede">{t("log.intro")}</p>
          <p>
            <Link className="button-like" to={`/campaigns/${encodeURIComponent(id)}/log`} data-testid="open-campaign-log">
              {t("log.open")}
            </Link>
          </p>
          <h2 id="campaign-dm-log">{t("campaign.dmLog")}</h2>
          <p className="lede">{t("campaign.dmLogIntro")}</p>
          <DmLog campaignId={id} />
        </TabPanel>

        <TabPanel name="novels" active={tab}>
          <NovelsSection source={{ kind: "campaign", id }} />
        </TabPanel>

        {carrying && <CarryForm campaign={c} characters={characters.data} onCancel={() => setCarrying(false)} />}
        <div className="actions">
          {!carrying && (
            <button type="button" onClick={() => setCarrying(true)}>
              {t("carry.open")}
            </button>
          )}
          <button
            type="button"
            className="danger"
            disabled={remove.isPending}
            onClick={async () =>
              (await confirm({
                title: t("campaign.deleteConfirm", { name: c.name }),
                body: tableZone && t("campaign.deleteKeepsZone"),
                confirm: t("dialog.delete"),
                danger: true,
              })) && remove.mutate()
            }
          >
            {t("campaign.delete")}
          </button>
        </div>
      </section>
    </PortraitStyleProvider>
  );
}

/** The campaign's banner: the current one, what a newer one is doing (waiting, painting, or its error when it failed),
 * and Paint again with an optional hint while the gate is open, else why not. Fetched again on `banner` and
 * `campaigns` events. */
function BannerSection({ campaign, banner }: { campaign: CampaignDetailShape; banner: CampaignBanner }) {
  const t = useT();
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const [hint, setHint] = useState("");
  const { id } = campaign;
  useEffect(() => {
    const refresh = () => client.invalidateQueries({ queryKey: queryKeys.campaign(id), exact: true });
    return subscribe({
      banner: (data) => (data as { campaign_id?: unknown } | null)?.campaign_id === id && refresh(),
      campaigns: (data) => (data as { id?: unknown } | null)?.id === id && refresh(),
    });
  }, [subscribe, client, id]);
  const paint = useMutation({
    mutationFn: () => paintBannerAgain(id, hint.trim()),
    onSuccess: () => {
      setHint("");
      client.invalidateQueries({ queryKey: queryKeys.campaign(id), exact: true });
    },
  });
  const pending = banner.pending;
  return (
    <div className="campaign-banner">
      {banner.image_id ? (
        <>
          <Banner src={bannerUrl(id, banner.image_id)} alt={t("banner.alt", { name: campaign.name })} variant="campaign" />
          {banner.from_module && <p className="hint">{t("banner.fromModule")}</p>}
        </>
      ) : (
        !pending && <p className="placeholder">{t("banner.none")}</p>
      )}
      {pending?.status === "waiting" && <p className="placeholder">{t("banner.waiting")}</p>}
      {pending?.status === "painting" && (
        <p className="placeholder" role="status">
          {queuedLine(t, pending) ?? t("banner.painting")}
        </p>
      )}
      {pending?.status === "failed" && (
        <p role="alert" className="notice error">
          {t("banner.failed")} {pending.error}
        </p>
      )}
      {banner.can_paint ? (
        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            paint.mutate();
          }}
        >
          <input aria-label={t("banner.hint")} placeholder={t("banner.hint")} value={hint} onChange={(e) => setHint(e.target.value)} />
          <button type="submit" disabled={paint.isPending || pending?.status === "painting"}>
            {t(banner.from_module ? "banner.paintOwn" : "banner.paintAgain")}
          </button>
        </form>
      ) : (
        banner.why_not && <p className="hint">{banner.why_not_code ? t(`banner.whyNot.${banner.why_not_code}`) : banner.why_not}</p>
      )}
      {paint.error && !(paint.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("campaign.changeFailed", { error: paint.error.message })}
        </p>
      )}
    </div>
  );
}

function CharacterRow({
  campaignId,
  character,
  busy,
  onChange,
}: {
  campaignId: string;
  character: TableCharacter;
  busy: boolean;
  onChange: (run: () => Promise<unknown>) => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const [name, setName] = useState(character.name);
  return (
    <li className="row">
      <span className="row-title">{character.name}</span>
      <form
        className="inline-form"
        onSubmit={(e) => {
          e.preventDefault();
          const next = name.trim();
          if (next && next !== character.name)
            onChange(() => renameCharacter(campaignId, character.id, next));
        }}
      >
        <input
          aria-label={t("campaign.nameOf", { name: character.name })}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim() || name.trim() === character.name}>
          {t("campaign.rename")}
        </button>
      </form>
      <button
        type="button"
        className="danger"
        disabled={busy}
        onClick={async () =>
          (await confirm({ title: t("campaign.removeConfirm", { name: character.name }), confirm: t("dialog.remove"), danger: true })) &&
          onChange(() => deleteCharacter(campaignId, character.id))
        }
      >
        {t("campaign.remove")}
      </button>
      <DepartureButtons campaignId={campaignId} character={character} busy={busy} onChange={onChange} />
    </li>
  );
}

/**
 * The campaign's portrait style, saved as it is chosen, with a sample portrait drawn in it. "As in Preferences" (null,
 * the default, DEL-252) draws PCs and NPCs in the styles Preferences pick as portraitgen's model; a style of its own
 * draws both in it. The sample shows the PCs' style the play state answers.
 */
function PortraitStyleEditor({ campaignId }: { campaignId: string }) {
  const t = useT();
  const client = useQueryClient();
  const settings = useQuery({ queryKey: playKeys.settings(campaignId), queryFn: () => getPlaySettings(campaignId) });
  const state = useQuery({ queryKey: playKeys.state(campaignId), queryFn: () => getPlayState(campaignId) });
  const save = useMutation({
    mutationFn: (style: string | null) => putPortraitStyle(campaignId, style),
    onSuccess: (stored) => {
      client.setQueryData(playKeys.settings(campaignId), stored);
      client.invalidateQueries({ queryKey: playKeys.state(campaignId) });
    },
  });
  const chosen = save.isPending ? save.variables : (settings.data?.portrait_style ?? null);
  const style = chosen ?? state.data?.portrait_style ?? PORTRAIT_STYLES[0];
  return (
    <div className="campaign-portraits">
      <div className="field">
        <label htmlFor="portrait-style">{t("portraits.style")}</label>
        <select
          id="portrait-style"
          value={chosen ?? ""}
          disabled={!settings.data || save.isPending}
          onChange={(e) => save.mutate(e.target.value || null)}
        >
          <option value="">{t("portraits.style.preferences")}</option>
          {PORTRAIT_STYLES.map((s) => (
            <option key={s} value={s}>
              {t(`portraits.style.${s}`)}
            </option>
          ))}
        </select>
      </div>
      <Portrait campaignId={campaignId} portrait={SAMPLE_PORTRAIT} name={t("portraits.sample")} size={96} style={style} />
      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("portraits.saveFailed", { error: save.error.message })}
        </p>
      )}
    </div>
  );
}

/** The campaign's choice of house rules, as the server has it, saved as a whole. */
function CampaignHouseRulesEditor({ campaignId }: { campaignId: string }) {
  const t = useT();
  const client = useQueryClient();
  const stored = useQuery({
    queryKey: queryKeys.campaignHouseRules(campaignId),
    queryFn: () => getCampaignHouseRules(campaignId),
  });
  const [draft, setDraft] = useState<CampaignHouseRules | null>(null);
  const save = useMutation({
    mutationFn: (choice: CampaignHouseRules) => putCampaignHouseRules(campaignId, choice),
    onSuccess: () => {
      setDraft(null);
      client.invalidateQueries({ queryKey: queryKeys.campaignHouseRules(campaignId) });
    },
  });
  if (stored.error && !(stored.error instanceof NeedsToken)) {
    return (
      <p role="alert" className="notice error">
        {t("houseRules.loadFailed", { error: stored.error.message })}
      </p>
    );
  }
  if (!stored.data) return <p className="placeholder">{t("houseRules.loading")}</p>;
  const value = draft ?? stored.data;
  return (
    <div className="campaign-house-rules">
      <HouseRulePicker value={value} onChange={setDraft} disabled={save.isPending} />
      {save.error && !(save.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("houseRules.saveFailed", { error: save.error.message })}
        </p>
      )}
      <button
        type="button"
        className="primary"
        disabled={!draft || save.isPending}
        onClick={() => draft && save.mutate(draft)}
      >
        {t("campaign.saveHouseRules")}
      </button>
    </div>
  );
}

/** The organiser's DM log: one row per beat, with the campaign's total. */
function DmLog({ campaignId }: { campaignId: string }) {
  const t = useT();
  const language = useLanguage();
  const log = useQuery({ queryKey: queryKeys.dmCosts(campaignId), queryFn: () => getDmCosts(campaignId) });
  const rows = log.data?.rows ?? [];
  const { shown, pager } = usePages(rows, 20, t("pager.labelled", { name: t("campaign.dmLog") }));
  if (log.error && !(log.error instanceof NeedsToken)) {
    return (
      <p role="alert" className="notice error">
        {t("dmLog.loadFailed", { error: log.error.message })}
      </p>
    );
  }
  if (!log.data) return <p className="placeholder">{t("dmLog.loading")}</p>;
  if (rows.length === 0) return <p className="placeholder">{t("dmLog.empty")}</p>;
  const usd = (cost: number | null) => (cost === null ? t("dmLog.noCost") : t("dmLog.usd", { amount: cost.toFixed(2) }));
  const sum = (pick: (row: DmCostRow) => number) => rows.reduce((total, row) => total + pick(row), 0);
  const costs = rows.map((row) => row.cost).filter((cost): cost is number => cost !== null);
  return (
    <div className="dm-log">
      <table className="sheet-table" aria-labelledby="campaign-dm-log">
        <thead>
          <tr>
            <th>{t("dmLog.beat")}</th>
            <th>{t("dmLog.tools")}</th>
            <th>{t("dmLog.inputTokens")}</th>
            <th>{t("dmLog.outputTokens")}</th>
            <th>{t("dmLog.cost")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr key={row.beat}>
              <td>
                {row.ask && <>{t("dmLog.ask")} · </>}
                <time dateTime={row.at}>{new Date(row.at).toLocaleString(language)}</time>
              </td>
              <td className="num">{row.tools}</td>
              <td className="num">{row.input}</td>
              <td className="num">{row.output}</td>
              <td className="num">{usd(row.cost)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">{t("dmLog.total")}</th>
            <td className="num">{sum((row) => row.tools)}</td>
            <td className="num">{sum((row) => row.input)}</td>
            <td className="num">{sum((row) => row.output)}</td>
            <td className="num">{usd(costs.length ? costs.reduce((a, b) => a + b, 0) : null)}</td>
          </tr>
        </tfoot>
      </table>
      {pager}
    </div>
  );
}

/** The Party tab's seats (players and tavern Task G3): who sits at the table, with their role and their avatar. */
function Seats({ campaignId }: { campaignId: string }) {
  const t = useT();
  const seats = useQuery({ queryKey: playKeys.seats(campaignId), queryFn: () => getSeats(campaignId) });
  return (
    <>
      <h2>{t("campaign.seats")}</h2>
      {seats.error ? (
        <p className="notice error" role="alert">
          {seats.error.message}
        </p>
      ) : !seats.data ? null : seats.data.length === 0 ? (
        <p className="placeholder">{t("campaign.noSeats")}</p>
      ) : (
        <ul className="rows campaign-seats" data-testid="campaign-seats">
          {seats.data.map((seat) => (
            <li key={seat.id} className="row">
              <PersonLink profile={seat.profile} name={seat.name} size={32}>
                <span className="seat-name">{seat.name}</span>
              </PersonLink>
              <span className="seat-role row-meta">{t(`play.role.${seat.role}`)}</span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
