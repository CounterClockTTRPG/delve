import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  CAMPAIGN_STATUSES,
  NO_HOUSE_RULES,
  NeedsToken,
  createCampaign,
  deleteCampaign,
  getModuleMetadata,
  getWorlds,
  listCampaigns,
  listModuleCategories,
  listModules,
  queryKeys,
  type CampaignListed,
  type CampaignStatus,
  type CampaignWorld,
  type Worlds,
} from "../api";
import { boardKeys, getBoard, zoneOfCampaign } from "../board/api";
import HouseRulePicker from "../campaign/HouseRulePicker";
import { useConfirm } from "../components/dialogs";
import { CardBanner, LayoutSwitch, useLayout, type Layout } from "../components/Layout";
import { usePages } from "../components/Pager";
import RowMenu from "../components/RowMenu";
import { useLanguage, useT, type Translate } from "../i18n";
import ModuleFilterBar from "../module/ModuleFilterBar";
import { NO_FILTER, filterModules, groupByCategory } from "../module/filter";
import { sortModules } from "../module/sort";
import { bannerUrl } from "../play/api";
import TableFaces from "../profile/TableFaces";
import { ago } from "../components/ago";

/** The ruleset and setting a module names in its metadata, as the server picks them when they are left out: its
 * `system` when that is a ruleset offered (else a preferred one offered, else the first offered), its `setting`
 * matching a setting's id or title (else a preferred one offered, else none). A preferred one is one its pack says a new
 * campaign takes (`preferred` in `/api/worlds`), as the server's `default_ruleset` and `default_setting` take it. */
function preselect(worlds: Worlds, metadata: Record<string, unknown> | undefined): CampaignWorld {
  const system = metadata?.system;
  const named = typeof metadata?.setting === "string" ? metadata.setting.trim().toLowerCase() : "";
  const ruleset =
    worlds.rulesets.find((r) => r.id === system) ??
    worlds.rulesets.find((r) => r.preferred) ??
    worlds.rulesets[0];
  const setting =
    worlds.settings.find((s) => named && [s.id.toLowerCase(), s.title.toLowerCase()].includes(named)) ??
    worlds.settings.find((s) => s.preferred);
  return { ruleset: ruleset?.id ?? "", setting: setting?.id ?? null };
}

// Here too, as before: `ago` moved out so My tables needn't load this screen (DEL-240).
export { ago };

/** The playtime in hours and minutes, or in minutes under an hour. */
export function playtime(t: Translate, seconds: number): string {
  const minutes = Math.floor(seconds / 60) % 60;
  const hours = Math.floor(seconds / 3600);
  return hours > 0
    ? t("campaigns.playtime", { hours: String(hours), minutes: String(minutes) })
    : t("campaigns.playtimeMinutes", { minutes: String(minutes) });
}

/** A status Delve doesn't know counts as in progress. */
function groupOf(c: CampaignListed): CampaignStatus {
  return (CAMPAIGN_STATUSES as readonly string[]).includes(c.status) ? (c.status as CampaignStatus) : "in_progress";
}

/** `/campaigns`: every campaign, grouped by its status (Complete folded), each with its module, its players, how
 * much it has been played and Delete; and "New campaign" from a module, with its ruleset, setting and house rules.
 * Table | Cards (DEL-207) switches the list to cards with each campaign's banner, or its name's first letter where it
 * has none, as the Modules list does; the choice is this browser's. */
export default function Campaigns() {
  const t = useT();
  const client = useQueryClient();
  const navigate = useNavigate();
  const campaigns = useQuery({ queryKey: queryKeys.campaigns, queryFn: listCampaigns });
  const modules = useQuery({ queryKey: queryKeys.modules, queryFn: listModules });
  const categories = useQuery({ queryKey: queryKeys.moduleCategories, queryFn: listModuleCategories }).data ?? [];
  const [name, setName] = useState("");
  // Set by a submit with no name, cleared by typing one.
  const [nameNeeded, setNameNeeded] = useState(false);
  // The command palette's New campaign opens this page at the form, its name to type.
  const { hash } = useLocation();
  useEffect(() => {
    if (hash === "#new-campaign") document.getElementById("campaign-name")?.focus();
  }, [hash]);
  const [layout, chooseLayout] = useLayout("delve.campaignsLayout");
  const [moduleId, setModuleId] = useState("");
  const [houseRules, setHouseRules] = useState(NO_HOUSE_RULES);
  const [picked, setPicked] = useState<Partial<CampaignWorld>>({});
  // A draft can't start a campaign until it is marked ready, and an empty module has nothing to play: neither is
  // offered. The rest by title (DEL-246).
  const playable = modules.data && sortModules(modules.data.filter((m) => !m.draft && !m.empty), "title");
  // The module filter (backlog 37) narrows the Module select; a module it hides isn't the one chosen.
  const [filter, setFilter] = useState(NO_FILTER);
  const offered = playable && filterModules(playable, filter);
  const chosen = (offered?.some((m) => m.id === moduleId) ? moduleId : offered?.[0]?.id) ?? "";
  const worlds = useQuery({ queryKey: queryKeys.worlds, queryFn: getWorlds });
  // Its metadata only: the map sources are big and not needed here (DEL-172).
  const module = useQuery({
    queryKey: queryKeys.moduleMetadata(chosen),
    queryFn: () => getModuleMetadata(chosen),
    enabled: !!chosen,
  });
  const world = worlds.data ? { ...preselect(worlds.data, module.data?.metadata), ...picked } : undefined;

  const create = useMutation({
    mutationFn: () => createCampaign(name.trim(), chosen, houseRules, world),
    onSuccess: (campaign) => {
      client.invalidateQueries({ queryKey: queryKeys.campaigns });
      navigate(`/campaigns/${encodeURIComponent(campaign.id)}`);
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setNameNeeded(true);
      document.getElementById("campaign-name")?.focus();
    } else if (chosen) create.mutate();
  }

  const language = useLanguage();
  const loadError = [campaigns.error, modules.error, worlds.error].find((e) => e && !(e instanceof NeedsToken));
  const noModules = playable?.length === 0;
  // Nothing yet, the first time: a guide instead of the bare form.
  const firstRun = modules.data?.length === 0 && campaigns.data?.length === 0;

  return (
    <section className="page">
      <h1>{t("area.campaigns")}</h1>

      {firstRun ? (
        <FirstRun />
      ) : (
        <form className="new-campaign" id="new-campaign" data-tour="new-campaign" onSubmit={submit}>
          {!!playable?.length && (
            <details className="module-filter-fold">
              <summary>{t("moduleFilter.label")}</summary>
              <ModuleFilterBar
                modules={playable}
                value={filter}
                idPrefix="campaign-module-filter"
                inForm
                onChange={(next) => {
                  setFilter(next);
                  setPicked({});
                }}
              />
            </details>
          )}
          <div className="inline-form">
            <div className="field">
              <label htmlFor="campaign-name">{t("campaigns.name")}</label>
              <input
                id="campaign-name"
                value={name}
                aria-invalid={nameNeeded || undefined}
                aria-describedby={nameNeeded ? "campaign-name-needed" : undefined}
                onChange={(e) => {
                  setName(e.target.value);
                  if (e.target.value.trim()) setNameNeeded(false);
                }}
              />
              {nameNeeded && (
                <span id="campaign-name-needed" role="alert" className="field-error">
                  {t("campaigns.nameNeeded")}
                </span>
              )}
            </div>
            <div className="field">
              <label htmlFor="campaign-module">{t("campaigns.module")}</label>
              <select
                id="campaign-module"
                value={chosen}
                onChange={(e) => {
                  setModuleId(e.target.value);
                  setPicked({});
                }}
                disabled={!offered?.length}
                aria-describedby={noModules ? "campaign-module-hint" : undefined}
              >
                {noModules ? (
                  <option value="">{t("campaigns.noModuleYet")}</option>
                ) : offered?.length === 0 ? (
                  <option value="">{t("moduleFilter.noneToPlay")}</option>
                ) : categories.length > 0 ? (
                  // Under their categories (DEL-114), as the Modules list shows them.
                  groupByCategory(offered ?? [], categories).map((group) => (
                    <optgroup key={group.category?.id ?? "none"} label={group.category?.name ?? t("moduleCategories.none")}>
                      {group.modules.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.title}
                        </option>
                      ))}
                    </optgroup>
                  ))
                ) : (
                  offered?.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.title}
                    </option>
                  ))
                )}
              </select>
              {noModules && (
                <p className="hint" id="campaign-module-hint">
                  {t("campaigns.noModules")} <Link to="/modules">{t("campaigns.toModules")}</Link>
                </p>
              )}
            </div>
            {world && (
              <>
                <div className="field">
                  <label htmlFor="campaign-ruleset">{t("campaigns.ruleset")}</label>
                  <select
                    id="campaign-ruleset"
                    value={world.ruleset}
                    onChange={(e) => setPicked({ ...picked, ruleset: e.target.value })}
                  >
                    {worlds.data?.rulesets.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.title}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="campaign-setting">{t("campaigns.setting")}</label>
                  <select
                    id="campaign-setting"
                    value={world.setting ?? ""}
                    onChange={(e) => setPicked({ ...picked, setting: e.target.value || null })}
                  >
                    {worlds.data?.settings.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.title}
                      </option>
                    ))}
                    <option value="">{t("campaigns.noSetting")}</option>
                  </select>
                </div>
              </>
            )}
            <button
              type="submit"
              className="primary"
              disabled={create.isPending || noModules || !modules.data || module.isLoading}
            >
              {t("campaigns.new")}
            </button>
          </div>
          <HouseRulePicker value={houseRules} onChange={setHouseRules} disabled={create.isPending} />
        </form>
      )}

      {create.error && !(create.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("campaigns.createFailed", { error: create.error.message })}
        </p>
      )}
      {loadError && (
        <p role="alert" className="notice error">
          {t("campaigns.loadFailed", { error: loadError.message })}
        </p>
      )}

      {firstRun ? null : campaigns.data ? (
        campaigns.data.length === 0 ? (
          <p className="placeholder">{t("campaigns.empty")}</p>
        ) : (
          <>
            <div className="campaign-list-head">
              <LayoutSwitch value={layout} onChange={chooseLayout} />
            </div>
            {CAMPAIGN_STATUSES.map((status) => {
              const listed = campaigns.data.filter((c) => groupOf(c) === status);
              return listed.length === 0 ? null : (
                <CampaignGroup key={status} status={status} listed={listed} language={language} layout={layout} />
              );
            })}
          </>
        )
      ) : !loadError ? (
        <p className="placeholder">{t("campaigns.loading")}</p>
      ) : null}
    </section>
  );
}

/** One status's campaigns, 20 a page, the page kept in the address as `?page.<status>=n` (pagination, 2026-10-23);
 * the complete ones folded away under their count. */
function CampaignGroup({
  status,
  listed,
  language,
  layout,
}: {
  status: CampaignStatus;
  listed: CampaignListed[];
  language: string;
  layout: Layout;
}) {
  const t = useT();
  const { shown, pager } = usePages(listed, 20, t("pager.labelled", { name: t(`campaigns.status.${status}`) }), {
    param: `page.${status}`,
  });
  const rows = (
    <>
      {layout === "cards" ? (
        <ul className="module-cards">
          {shown.map((c) => (
            <CampaignCard key={c.id} campaign={c} language={language} />
          ))}
        </ul>
      ) : (
        <ul className="rows">
          {shown.map((c) => (
            <CampaignRow key={c.id} campaign={c} language={language} />
          ))}
        </ul>
      )}
      {pager}
    </>
  );
  return (
    <section className="campaign-group" data-status={status}>
      {status === "complete" ? (
        <details>
          <summary>{t("campaigns.completeCount", { count: String(listed.length) })}</summary>
          {rows}
        </details>
      ) : (
        <>
          <h2>{t(`campaigns.status.${status}`)}</h2>
          {rows}
        </>
      )}
    </section>
  );
}

/** The first screen, with no module and no campaign: the three steps to a game, each a link. */
function FirstRun() {
  const t = useT();
  return (
    <section className="first-run" aria-labelledby="first-run-title">
      <h2 id="first-run-title">{t("firstRun.title")}</h2>
      <ol>
        <li>
          <Link to="/modules">{t("firstRun.module")}</Link>
        </li>
        <li>
          <Link to="/campaigns">{t("firstRun.campaign")}</Link>
        </li>
        <li>
          <Link to="/play">{t("firstRun.play")}</Link>
        </li>
      </ol>
    </section>
  );
}

/** A campaign as a card (DEL-207): its banner, its name, its module, when it was last played, who sits at its table
 * with its open places (DEL-230) and its menu. */
function CampaignCard({ campaign: c, language }: { campaign: CampaignListed; language: string }) {
  const t = useT();
  return (
    <li className="module-card">
      <Link to={`/campaigns/${encodeURIComponent(c.id)}`} className="module-card-link">
        <CardBanner src={c.banner ? bannerUrl(c.id, c.banner, "card") : null} title={c.name} />
        <span className="module-card-title">{c.name}</span>
      </Link>
      <div className="module-card-meta">
        <span className="row-meta">{t("campaigns.playing", { module: c.module_title, revision: String(c.revision) })}</span>
        <span className="row-meta">
          {c.last_played ? t("campaigns.lastPlayed", { when: ago(c.last_played, language) }) : t("campaigns.notPlayed")}
        </span>
        <TableFaces people={c.people} slots={c.slots} taken={c.taken} />
        <CampaignMenu campaign={c} />
      </div>
    </li>
  );
}

function CampaignRow({ campaign: c, language }: { campaign: CampaignListed; language: string }) {
  const t = useT();
  return (
    <li className="row">
      <Link to={`/campaigns/${encodeURIComponent(c.id)}`} className="row-title">
        {c.name}
      </Link>
      <span className="row-meta">{t("campaigns.playing", { module: c.module_title, revision: String(c.revision) })}</span>
      {c.players.length > 0 && <span className="row-meta">{t("campaigns.players", { names: c.players.join(", ") })}</span>}
      <TableFaces people={c.people} slots={c.slots} taken={c.taken} />
      <span className="row-meta">
        {c.last_played ? t("campaigns.lastPlayed", { when: ago(c.last_played, language) }) : t("campaigns.notPlayed")}
      </span>
      {c.sessions > 0 && (
        <>
          <span className="row-meta">
            {c.sessions === 1 ? t("campaigns.sessions.one") : t("campaigns.sessions", { count: String(c.sessions) })}
          </span>
          <span className="row-meta">{playtime(t, c.playtime_s)}</span>
        </>
      )}
      <CampaignMenu campaign={c} />
    </li>
  );
}

/** A campaign's menu, on its row and its card: Play, its page, its log (out of the play head), Carry the party on
 * and Delete. */
function CampaignMenu({ campaign: c }: { campaign: CampaignListed }) {
  const t = useT();
  const client = useQueryClient();
  const confirm = useConfirm();
  const remove = useMutation({
    mutationFn: () => deleteCampaign(c.id),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.campaigns }),
  });
  return (
    <>
      <RowMenu
        label={t("rowMenu.of", { name: c.name })}
        actions={[
          { label: t("campaigns.playIt"), to: `/play/${encodeURIComponent(c.id)}` },
          { label: t("campaigns.openPage"), to: `/campaigns/${encodeURIComponent(c.id)}` },
          { label: t("log.open"), to: `/campaigns/${encodeURIComponent(c.id)}/log` },
          { label: t("carry.open"), to: `/campaigns/${encodeURIComponent(c.id)}?carry` },
          {
            label: t("dialog.delete"),
            danger: true,
            disabled: remove.isPending,
            onSelect: async () => {
              // The board is asked only now: whether the campaign has a zone, which its delete leaves to its members.
              const board = await client.fetchQuery({ queryKey: boardKeys.all, queryFn: getBoard }).catch(() => undefined);
              const sure = await confirm({
                title: t("campaign.deleteConfirm", { name: c.name }),
                body: zoneOfCampaign(board, c.id) && t("campaign.deleteKeepsZone"),
                confirm: t("dialog.delete"),
                danger: true,
              });
              if (sure) remove.mutate();
            },
          },
        ]}
      />
      {remove.error && !(remove.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("campaigns.deleteFailed", { error: remove.error.message })}
        </p>
      )}
    </>
  );
}
