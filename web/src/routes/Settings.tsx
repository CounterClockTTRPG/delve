import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { NeedsToken } from "../api";
import { useT } from "../i18n";
import { listSettings, settingKeys } from "../setting/api";

/** `/settings`: the install's settings, the worlds its campaigns play in, each a link to its lore, calendar and maps. */
export default function Settings() {
  const t = useT();
  const settings = useQuery({ queryKey: settingKeys.list, queryFn: listSettings });
  return (
    <section className="page">
      <h1>{t("settings.title")}</h1>

      {settings.error && !(settings.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("settings.loadFailed", { error: settings.error.message })}
        </p>
      )}

      {settings.data ? (
        settings.data.length === 0 ? (
          <p className="placeholder">{t("settings.empty")}</p>
        ) : (
          <ul className="rows">
            {settings.data.map((s) => (
              <li key={s.id} className="row">
                <Link to={`/settings/${encodeURIComponent(s.id)}`} className="row-title">
                  {s.title}
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : !settings.error ? (
        <p className="placeholder">{t("settings.loading")}</p>
      ) : null}
    </section>
  );
}
