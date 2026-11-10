import { useQuery } from "@tanstack/react-query";
import { Paintbrush } from "lucide-react";
import { useParams } from "react-router-dom";
import { isOrganiser } from "../account/api";
import { useMe } from "../account/useMe";
import { Markdown } from "../house-rules/RuleEditor";
import { useT } from "../i18n";
import { getMonsterPicture, monsterKeys } from "../monsters/api";
import { MonsterFace, PaintMonster } from "../monsters/MonsterPictures";
import { getEntry, rulesetKeys } from "./api";
import { Crumbs, DataTable, Fields, HouseRuleTag, LoadFailed, NotFound, isNotFound, useCampaign } from "./parts";
import styles from "./Rulesets.module.css";

/**
 * `/rulesets/:rulesetId/:section/:entryId`: one entry in full, at an address to share: its fields (labelled, the
 * key as the fallback), its text as Markdown and its table (a class's progression, an ability's scores). A house
 * rule is marked; the server has cut its DM Notes for a reader who isn't an organiser. An entry that isn't there,
 * or that the reader may not see, is the same "not found". A monster shows the picture of its kind (DEL-275), and an
 * organiser has one painted, or painted again, for every table.
 */
export default function EntryPage() {
  const t = useT();
  const { rulesetId = "", section = "", entryId = "" } = useParams();
  const campaign = useCampaign();
  const entry = useQuery({
    queryKey: rulesetKeys.entry(rulesetId, section, entryId, campaign),
    queryFn: () => getEntry(rulesetId, section, entryId, campaign),
  });
  const data = entry.data;

  return (
    <section className="page">
      <Crumbs rulesetId={rulesetId} section={section} />
      <LoadFailed error={entry.error} />
      {isNotFound(entry.error) && <NotFound />}

      {data && (
        <article className={styles.entry}>
          <header className={styles.head}>
            <h1>{data.name}</h1>
            {data.house_rule && <HouseRuleTag />}
          </header>
          {section === "monsters" && <MonsterPicture name={data.name} />}
          <Fields fields={data.fields} />
          {data.text && (
            <div className={styles.text}>
              <Markdown source={data.text} />
            </div>
          )}
          {data.table !== null && data.table !== undefined && <DataTable value={data.table} />}
        </article>
      )}

      {entry.isPending && <p className="placeholder">{t("rulesets.loading")}</p>}
    </section>
  );
}

/** How often a picture being painted is asked about again, in ms. */
const PAINTING_POLL = 4000;

/** The monster's picture, enlarging on a click; an organiser's Paint, or Paint again (DEL-275). */
function MonsterPicture({ name }: { name: string }) {
  const t = useT();
  const me = useMe();
  // Without an answer from /api/me this is the owner's own screen.
  const organiser = me.isError || (me.data !== undefined && (me.data.account ? isOrganiser(me.data.account) : !me.data.seat));
  const state = useQuery({
    queryKey: monsterKeys.state(name),
    queryFn: () => getMonsterPicture(name),
    refetchInterval: (query) => (query.state.data?.painting ? PAINTING_POLL : false),
  });
  const picture = state.data;
  if (!picture || (!picture.picture && !organiser)) return null;
  return (
    <figure className={styles.monsterPicture} data-testid="monster-picture">
      {picture.picture ? (
        <MonsterFace name={name} slug={picture.slug} version={picture.version} size={160} />
      ) : (
        <span className={styles.noPicture}>{t("monsters.none")}</span>
      )}
      {organiser && (
        <figcaption>
          {picture.painting ? (
            <span className="hint" role="status">
              {t("monsters.paintingNow", { name })}
            </span>
          ) : (
            <PaintMonster
              name={name}
              again={picture.picture}
              trigger={(open) => (
                <button type="button" data-testid="monster-paint" onClick={open}>
                  <Paintbrush size={16} aria-hidden="true" /> {t(picture.picture ? "monsters.paintAgain" : "monsters.paint", { name })}
                </button>
              )}
            />
          )}
        </figcaption>
      )}
    </figure>
  );
}
