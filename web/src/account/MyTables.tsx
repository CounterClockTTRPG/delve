import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useLanguage, useT } from "../i18n";
import { bannerUrl } from "../play/api";
import { ago } from "../components/ago";
import { accountKeys, getMyTables } from "./api";
import NextSessionLine from "../play/NextSession";
import MyRequests from "./MyRequests";
import TableFaces from "../profile/TableFaces";
import "./account.css";

/**
 * `/tables`, an account's own page (players and tavern Task E3): a card for each table it has a seat at, the most
 * recently played first and the complete ones last, grayed, to open rather than play, with who sits at it (DEL-217), with the campaign's banner, its module, the account's role there, its last session, and Play;
 * then the account's requests to join public tables (DEL-204), and a way to Find a table.
 */
export default function MyTables() {
  const t = useT();
  const language = useLanguage();
  const tables = useQuery({ queryKey: accountKeys.tables, queryFn: getMyTables });
  return (
    <section className="page">
      <div className="page-head">
        <h1>{t("tables.title")}</h1>
        <Link className="button-like" to="/tables/find" data-testid="find-a-table">
          {t("find.title")}
        </Link>
      </div>
      {tables.isPending && <p className="placeholder">{t("preferences.loading")}</p>}
      {tables.error && (
        <p className="notice error" role="alert">
          {tables.error.message}
        </p>
      )}
      {tables.data?.length === 0 && <p className="placeholder">{t("tables.none")}</p>}
      {tables.data && tables.data.length > 0 && (
        <ul className="my-tables">
          {tables.data.map((table) => {
            const complete = table.status === "complete";
            return (
            <li
              key={table.campaign_id}
              className={complete ? "my-table complete" : "my-table"}
              data-testid={`my-table-${table.campaign_id}`}
            >
              {table.banner && <img className="my-table-banner" src={bannerUrl(table.campaign_id, undefined, "card")} alt="" />}
              <div className="my-table-body">
                <h2>{table.name}</h2>
                {table.module_title && <span>{table.module_title}</span>}
                <span className="row-meta">
                  {t(`play.role.${table.role}`)}
                  {complete && <span className="my-table-status">{t("campaigns.status.complete")}</span>}
                </span>
                <TableFaces people={table.people} slots={table.slots} taken={table.taken} />
                {!complete && <NextSessionLine sessions={table.next_sessions} className="next-session row-meta" />}
                <span className="row-meta">
                  {table.last_played_at
                    ? t("tables.lastPlayed", { session: String(table.session_number), ago: ago(table.last_played_at, language) })
                    : t("tables.notPlayed")}
                </span>
                <Link
                  className={complete ? "button-like" : "button-like primary"}
                  to={`/play/${encodeURIComponent(table.campaign_id)}`}
                  data-testid={`my-table-play-${table.campaign_id}`}
                >
                  {t(complete ? "tables.open" : "tables.play")}
                </Link>
              </div>
            </li>
            );
          })}
        </ul>
      )}
      <MyRequests />
    </section>
  );
}
