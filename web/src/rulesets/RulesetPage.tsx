import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { listCampaigns, queryKeys } from "../api";
import { useDebounce } from "../editor/useDebounce";
import { useT } from "../i18n";
import { useMe } from "../account/useMe";
import { rulesetKeys, searchRuleset } from "./api";
import {
  Crumbs,
  LoadFailed,
  NotFound,
  entryHref,
  isNotFound,
  sectionHref,
  sectionLabel,
  sectionLine,
  useCampaign,
  useRuleset,
  withCampaign,
} from "./parts";
import styles from "./Rulesets.module.css";

/**
 * `/rulesets/:rulesetId`: the ruleset's sections as cards, each with what it holds and how many, and a search by name
 * across them (250 ms after the last key). An organiser without a seat chooses whose house rules show beside the
 * book; the choice is the address's `?campaign=`, which every link of the area keeps. A seat's are its campaign's.
 */
export default function RulesetPage() {
  const t = useT();
  const { rulesetId = "" } = useParams();
  const campaign = useCampaign();
  const ruleset = useRuleset(rulesetId);
  const [q, setQ] = useState("");
  const query = useDebounce(q.trim(), 250);
  const hits = useQuery({
    queryKey: rulesetKeys.search(rulesetId, query, campaign),
    queryFn: () => searchRuleset(rulesetId, query, campaign),
    enabled: query !== "",
    placeholderData: keepPreviousData,
  });

  return (
    <section className="page">
      <Crumbs rulesetId={rulesetId} />
      <LoadFailed error={ruleset.error ?? hits.error} />
      {isNotFound(ruleset.error) && <NotFound />}

      {ruleset.data && (
        <>
          <h1>{ruleset.data.title}</h1>
          <div className={`toolbar ${styles.toolbar}`}>
            <input
              type="search"
              className={styles.search}
              aria-label={t("rulesets.search")}
              placeholder={t("rulesets.search")}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <CampaignPicker />
          </div>

          {query !== "" &&
            hits.data &&
            (hits.data.length === 0 ? (
              <p className="placeholder">{t("rulesets.noHits")}</p>
            ) : (
              <ul className="rows">
                {hits.data.map((hit) => (
                  <li key={`${hit.section}:${hit.id}`} className="row">
                    <Link to={withCampaign(entryHref(rulesetId, hit.section, hit.id), campaign)} className="row-title">
                      {hit.name}
                    </Link>
                    <span className="row-meta">{sectionLabel(t, hit.section)}</span>
                  </li>
                ))}
              </ul>
            ))}

          <ul className={styles.cards}>
            {ruleset.data.sections.map((section) => (
              <li key={section.key}>
                <Link to={withCampaign(sectionHref(rulesetId, section.key), campaign)} className={`choice ${styles.card}`}>
                  <span className="choice-title">{sectionLabel(t, section.key)}</span>
                  {sectionLine(t, section.key) && <span className="row-meta">{sectionLine(t, section.key)}</span>}
                  <span className={styles.count}>{t("rulesets.count", { count: String(section.count) })}</span>
                </Link>
              </li>
            ))}
          </ul>
          {ruleset.data.notice && <p className={styles.notice}>{ruleset.data.notice}</p>}
        </>
      )}

      {ruleset.isPending && <p className="placeholder">{t("rulesets.loading")}</p>}
    </section>
  );
}

/** "House rules of": no campaign, or one of the install's, for the owner and organisers without a seat only (not for a
 * player's account, which has no seat in `/api/me` either). */
function CampaignPicker() {
  const t = useT();
  const campaign = useCampaign();
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const unseated = me.data !== undefined && !me.data.seat && me.data.principal.roles.includes("organiser");
  const campaigns = useQuery({ queryKey: queryKeys.campaigns, queryFn: listCampaigns, enabled: unseated });
  if (!unseated) return null;
  const choose = (id: string) => {
    const next = new URLSearchParams(params);
    if (id) next.set("campaign", id);
    else next.delete("campaign");
    setParams(next, { replace: true });
  };
  return (
    <div className={`field ${styles.picker}`}>
      <label htmlFor="rulesets-campaign">{t("rulesets.houseRulesOf")}</label>
      <select id="rulesets-campaign" value={campaign ?? ""} onChange={(e) => choose(e.target.value)}>
        <option value="">{t("rulesets.noCampaign")}</option>
        {campaigns.data?.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
    </div>
  );
}
