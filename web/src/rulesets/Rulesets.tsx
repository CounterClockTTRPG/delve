import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useT } from "../i18n";
import { listRulesets, rulesetKeys } from "./api";
import { BackToTable, LoadFailed, rulesetHref, useCampaign, withCampaign } from "./parts";
import styles from "./Rulesets.module.css";

/** `/rulesets`: the installed rulesets, a card each, even when there is one, so a second changes nothing. */
export default function Rulesets() {
  const t = useT();
  const campaign = useCampaign();
  const rulesets = useQuery({ queryKey: rulesetKeys.list, queryFn: listRulesets });
  return (
    <section className="page">
      <BackToTable />
      <h1>{t("rulesets.title")}</h1>
      <p className="lede">{t("rulesets.lede")}</p>

      <LoadFailed error={rulesets.error} />

      {rulesets.data ? (
        rulesets.data.length === 0 ? (
          <p className="placeholder">{t("rulesets.empty")}</p>
        ) : (
          <ul className={styles.cards}>
            {rulesets.data.map((r) => (
              <li key={r.id}>
                <Link to={withCampaign(rulesetHref(r.id), campaign)} className={`choice ${styles.card}`}>
                  <span className="choice-title">{r.title}</span>
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : !rulesets.error ? (
        <p className="placeholder">{t("rulesets.loading")}</p>
      ) : null}
    </section>
  );
}
