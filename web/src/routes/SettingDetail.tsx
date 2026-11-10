import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { NeedsToken } from "../api";
import { useT, type MessageKey } from "../i18n";
import FactsTab from "../setting/FactsTab";
import LoreTab from "../setting/LoreTab";
import MapsTab from "../setting/MapsTab";
import ProposalsTab from "../setting/ProposalsTab";
import TransferTab from "../setting/TransferTab";
import { getSetting, settingKeys, type CalendarView, type SettingInfo } from "../setting/api";
import styles from "../setting/Setting.module.css";

/**
 * A tab of a setting's page: its `?tab=` id, its label, a count beside the label when there is one, and what it shows.
 */
type SettingTab = {
  id: string;
  label: MessageKey;
  count?: (setting: SettingInfo) => number;
  element: (setting: SettingInfo) => ReactNode;
};

const TABS: SettingTab[] = [
  { id: "lore", label: "setting.tab.lore", element: (s) => <LoreTab settingId={s.id} kinds={s.kinds} /> },
  { id: "facts", label: "setting.tab.facts", element: (s) => <FactsTab settingId={s.id} /> },
  {
    id: "proposals",
    label: "setting.tab.proposals",
    count: (s) => s.counts.proposals,
    element: (s) => <ProposalsTab settingId={s.id} />,
  },
  { id: "maps", label: "setting.tab.maps", element: (s) => <MapsTab settingId={s.id} /> },
  { id: "calendar", label: "setting.tab.calendar", element: (s) => <CalendarTab calendar={s.calendar} /> },
  // This install's additions, as a file for another Delve, and one imported here (DEL-366).
  { id: "transfer", label: "setting.tab.transfer", element: (s) => <TransferTab settingId={s.id} /> },
];

/** `/settings/:settingId`: one setting, in tabs chosen by `?tab=` (Lore by default). */
export default function SettingDetail() {
  const t = useT();
  const { settingId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const setting = useQuery({ queryKey: settingKeys.one(settingId), queryFn: () => getSetting(settingId) });
  const tab = TABS.find((row) => row.id === params.get("tab")) ?? TABS[0];
  const count = (row: SettingTab) => (setting.data && row.count?.(setting.data)) || 0;
  const open = (id: string) => setParams(id === TABS[0].id ? {} : { tab: id }, { replace: true });

  return (
    <section className="page">
      <p>
        <Link to="/settings">{t("settings.title")}</Link>
      </p>

      {setting.error && !(setting.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("setting.loadFailed", { error: setting.error.message })}
        </p>
      )}

      {setting.data ? (
        <>
          <h1>{setting.data.title}</h1>
          <div role="tablist" className={`view-tabs ${styles.tabs}`} aria-label={t("setting.tabs")}>
            {TABS.map((row) => (
              <button
                key={row.id}
                type="button"
                role="tab"
                id={`setting-tab-${row.id}`}
                aria-selected={tab.id === row.id}
                aria-controls={`setting-panel-${row.id}`}
                className="view-tab"
                onClick={() => open(row.id)}
              >
                {t(row.label)}
                {count(row) > 0 && <> <span className="tag">{count(row)}</span></>}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`setting-panel-${tab.id}`} aria-labelledby={`setting-tab-${tab.id}`}>
            {tab.element(setting.data)}
          </div>
        </>
      ) : !setting.error ? (
        <p className="placeholder">{t("setting.loading")}</p>
      ) : null}
    </section>
  );
}

/** The setting's year: its months in order, each with its days, season and weather season, the festivals marked. */
function CalendarTab({ calendar }: { calendar: CalendarView | null }) {
  const t = useT();
  if (!calendar) return <p className="placeholder">{t("setting.calendar.none")}</p>;
  return (
    <>
      <p>{t("setting.calendar.era", { era: calendar.era })}</p>
      <table className={styles.calendar}>
        <thead>
          <tr>
            <th scope="col">{t("setting.calendar.month")}</th>
            <th scope="col">{t("setting.calendar.days")}</th>
            <th scope="col">{t("setting.calendar.season")}</th>
            <th scope="col">{t("setting.calendar.weather")}</th>
            <th scope="col">
              <span className="visually-hidden">{t("setting.calendar.festival")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {calendar.months.map((month) => (
            <tr key={month.name} className={month.festival ? styles.festival : undefined}>
              <td>{month.name}</td>
              <td>{month.days}</td>
              <td>{month.season}</td>
              <td>{month.weather_season}</td>
              <td>{month.festival && <span className="tag">{t("setting.calendar.festival")}</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
