import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, NeedsToken } from "../api";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import PageForm from "../setting/PageForm";
import SettingText from "../setting/SettingText";
import { originTag } from "../setting/LoreTab";
import { deletePage, getPage, getSetting, settingKeys, type SettingPage as Page } from "../setting/api";
import styles from "../setting/Setting.module.css";

const settingHref = (settingId: string) => `/settings/${encodeURIComponent(settingId)}`;
const pageHrefOf = (settingId: string) => (title: string) => `${settingHref(settingId)}/pages/${encodeURIComponent(title)}`;

/**
 * `/settings/:settingId/pages/:title`: a setting page, as an organiser reads it, DM-only sections marked. Edit opens
 * the form; an override can be reverted to the book's page, and an addition deleted. A page that isn't there offers
 * to write it.
 */
export default function SettingPage() {
  const t = useT();
  const { settingId = "", title = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(false);
  const setting = useQuery({ queryKey: settingKeys.one(settingId), queryFn: () => getSetting(settingId) });
  const page = useQuery({ queryKey: settingKeys.page(settingId, title), queryFn: () => getPage(settingId, title) });
  const pageHref = pageHrefOf(settingId);
  // A revert brings the book's page back; a deleted addition leaves nothing, so the setting opens.
  const remove = useMutation({
    mutationFn: () => deletePage(settingId, page.data!.title),
    onSuccess: () => {
      if (page.data?.origin === "addition") navigate(settingHref(settingId));
      client.invalidateQueries({ queryKey: settingKeys.one(settingId) });
    },
  });
  const missing = page.error instanceof ApiError && page.error.status === 404;
  const failed = [page.error, remove.error].find((e) => e && !(e instanceof NeedsToken) && !(e === page.error && missing));

  const saved = (p: Page) => {
    setEditing(false);
    client.setQueryData(settingKeys.page(settingId, title), p);
    client.invalidateQueries({ queryKey: settingKeys.one(settingId) });
  };

  return (
    <section className="page">
      <p>
        <Link to={settingHref(settingId)}>{setting.data?.title ?? settingId}</Link>
      </p>

      {failed && (
        <p role="alert" className="notice error">
          {t("setting.loadFailed", { error: failed.message })}
        </p>
      )}

      {missing && (
        <>
          <h1>{title}</h1>
          <p className="placeholder">
            <span>{t("setting.noPage", { title })}</span>{" "}
            <Link to={`${settingHref(settingId)}/new-page?title=${encodeURIComponent(title)}`}>{t("setting.writeIt")}</Link>
          </p>
        </>
      )}

      {page.data && (
        <article className={styles.page}>
          <header className={styles.main}>
            <h1>{page.data.title}</h1>
            {page.data.redirected_from && (
              <p className={styles.redirected}>{t("setting.redirectedFrom", { title: page.data.redirected_from })}</p>
            )}
            <div className={styles.tags}>
              {page.data.kind && <span className="tag">{page.data.kind}</span>}
              {originTag(t, page.data.origin)}
              {page.data.dm_only && <span className="dm-only-mark">{t("setting.dmOnly")}</span>}
            </div>
          </header>

          <div className={styles.side}>
            {!editing && (
              <div className="actions">
                <button type="button" onClick={() => setEditing(true)}>
                  {t("setting.edit")}
                </button>
                {page.data.revertible && (
                  <button
                    type="button"
                    disabled={remove.isPending}
                    onClick={async () =>
                      (await confirm({ title: t("setting.revertConfirm", { title: page.data!.title }), confirm: t("setting.revert") })) &&
                      remove.mutate()
                    }
                  >
                    {t("setting.revert")}
                  </button>
                )}
                {page.data.origin === "addition" && (
                  <button
                    type="button"
                    className="danger"
                    disabled={remove.isPending}
                    onClick={async () =>
                      (await confirm({
                        title: t("setting.deleteConfirm", { title: page.data!.title }),
                        confirm: t("setting.delete"),
                        danger: true,
                      })) && remove.mutate()
                    }
                  >
                    {t("setting.delete")}
                  </button>
                )}
              </div>
            )}
            {Object.keys(page.data.fields).length > 0 && (
              <dl className={styles.fieldList}>
                {Object.entries(page.data.fields).map(([key, value]) => (
                  <Fragment key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </Fragment>
                ))}
              </dl>
            )}
          </div>

          <div className={styles.main}>
            {editing ? (
              <PageForm
                settingId={settingId}
                kinds={setting.data?.kinds ?? []}
                page={page.data}
                onSaved={saved}
                onCancel={() => setEditing(false)}
              />
            ) : (
              <SettingText text={page.data.text} pageHref={pageHref} dmMarked />
            )}
          </div>
        </article>
      )}

      {page.isPending && <p className="placeholder">{t("setting.loading")}</p>}
    </section>
  );
}

/** `/settings/:settingId/new-page?title=`: an empty page to write; saved, it opens. */
export function NewSettingPage() {
  const t = useT();
  const { settingId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const setting = useQuery({ queryKey: settingKeys.one(settingId), queryFn: () => getSetting(settingId) });
  const pageHref = pageHrefOf(settingId);
  return (
    <section className="page">
      <p>
        <Link to={settingHref(settingId)}>{setting.data?.title ?? settingId}</Link>
      </p>
      <h1>{t("setting.newPage")}</h1>
      <PageForm
        settingId={settingId}
        kinds={setting.data?.kinds ?? []}
        page={null}
        initialTitle={params.get("title") ?? ""}
        onSaved={(p) => {
          client.setQueryData(settingKeys.page(settingId, p.title), p);
          client.invalidateQueries({ queryKey: settingKeys.one(settingId) });
          navigate(pageHref(p.title));
        }}
      />
    </section>
  );
}
