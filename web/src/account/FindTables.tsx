import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useT } from "../i18n";
import TableAbout from "../play/TableAbout";
import PersonLink from "../profile/PersonLink";
import TableFaces from "../profile/TableFaces";
import { MESSAGE_CHARS, accountKeys, askToJoin, listPublicTables, type PublicTable } from "./api";
import "./account.css";

/**
 * `/tables/find`, Find a table (DEL-204): the public tables of this Delve, for any logged-in account, the most recently
 * played first. Each shows its module and ruleset, its host, its places, what it tells its players and its house rules,
 * then what this account can do: Open the table it sits at, see where its request stands (My tables holds the thread),
 * or Ask to join with a short note to the host. A full table takes no request.
 */
export default function FindTables() {
  const t = useT();
  const tables = useQuery({ queryKey: accountKeys.findTables, queryFn: listPublicTables });
  return (
    <section className="page">
      <h1>{t("find.title")}</h1>
      <p className="lede">{t("find.intro")}</p>
      {tables.isPending && <p className="placeholder">{t("preferences.loading")}</p>}
      {tables.error && (
        <p className="notice error" role="alert">
          {tables.error.message}
        </p>
      )}
      {tables.data?.length === 0 && <p className="placeholder">{t("find.none")}</p>}
      {tables.data && tables.data.length > 0 && (
        <ul className="find-tables">
          {tables.data.map((table) => (
            <li key={table.campaign_id} className="find-table" data-testid={`find-table-${table.campaign_id}`}>
              <FoundTable table={table} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FoundTable({ table }: { table: PublicTable }) {
  const t = useT();
  const client = useQueryClient();
  // Asking to play, or to watch (DEL-215): a watcher takes no place, so a full table may still be watched.
  const [asking, setAsking] = useState<"player" | "observer" | null>(null);
  const [note, setNote] = useState("");
  const ask = useMutation({
    mutationFn: (role: "player" | "observer") => askToJoin(table.campaign_id, note.trim(), role),
    onSuccess: () => {
      setAsking(null);
      setNote("");
      client.invalidateQueries({ queryKey: accountKeys.findTables });
      client.invalidateQueries({ queryKey: accountKeys.requests });
    },
  });
  const waiting = table.request?.status === "pending";
  const watchable = (table.observers ?? "anyone") !== "nobody";
  const askToWatch = watchable && (
    <button type="button" data-testid="find-ask-watch" onClick={() => setAsking("observer")}>
      {t("find.askToWatch")}
    </button>
  );
  return (
    <>
      <div className="find-table-head">
        <h2>{table.name}</h2>
        {table.module_title && <span>{table.module_title}</span>}
        <span className="row-meta">
          {[table.ruleset_title ?? table.ruleset, table.setting_title].filter(Boolean).join(", ")}
        </span>
        {table.host && (
          <span className="find-host">
            <PersonLink profile={table.host.profile} name={table.host.display_name}>
              {t("find.host", { name: table.host.display_name })}
            </PersonLink>
          </span>
        )}
        <TableFaces people={table.people} slots={table.slots} taken={table.taken} />
      </div>
      <TableAbout about={table} heading={false} places={!table.people} />
      <div className="find-table-actions">
        {table.seated ? (
          <Link className="button-like primary" to={`/play/${encodeURIComponent(table.campaign_id)}`}>
            {t("find.open")}
          </Link>
        ) : waiting ? (
          <p className="row-meta" data-testid="find-waiting">
            {t("find.waiting")} <Link to="/tables">{t("find.seeRequest")}</Link>
          </p>
        ) : asking ? (
          <form
            className="find-ask"
            onSubmit={(e) => {
              e.preventDefault();
              ask.mutate(asking);
            }}
          >
            <label htmlFor={`note-${table.campaign_id}`}>{t("find.note")}</label>
            <textarea
              id={`note-${table.campaign_id}`}
              rows={3}
              maxLength={MESSAGE_CHARS}
              value={note}
              placeholder={t("find.notePlaceholder")}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="request-actions">
              <button type="submit" className="primary" data-testid="find-send" disabled={ask.isPending}>
                {t(asking === "observer" ? "find.sendWatch" : "find.send")}
              </button>
              <button type="button" onClick={() => setAsking(null)}>
                {t("dialog.cancel")}
              </button>
            </div>
          </form>
        ) : table.full ? (
          <>
            <p className="row-meta">{t("find.full")}</p>
            {askToWatch}
          </>
        ) : (
          <>
            {table.request?.status === "declined" && <p className="row-meta">{t("find.declinedBefore")}</p>}
            <button type="button" className="primary" data-testid="find-ask" onClick={() => setAsking("player")}>
              {t("find.ask")}
            </button>
            {askToWatch}
          </>
        )}
        {ask.error && (
          <p className="notice error" role="alert">
            {ask.error.message}
          </p>
        )}
      </div>
    </>
  );
}
