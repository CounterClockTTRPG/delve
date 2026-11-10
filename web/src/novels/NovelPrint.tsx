// `/novels/:id/print`: a novel for print, as the module's print view prints a module: a title page, then each written
// chapter on a page of its own. The PDF comes from the browser's Print dialog; Delve has no PDF library.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { useLanguage, useT } from "../i18n";
import { useNoLook } from "../looks/looks";
import mapStyles from "../routes/MapPrint.module.css";
import { getNovel, novelKeys, writtenChapters } from "./api";
import { chapterHtml } from "./markdown";
import { novelByline } from "./NovelReader";
import styles from "./NovelPrint.module.css";

export default function NovelPrint() {
  const { id = "" } = useParams();
  const t = useT();
  useNoLook();
  const language = useLanguage();
  const novel = useQuery({ queryKey: novelKeys.one(id), queryFn: () => getNovel(id) });
  const chapters = useMemo(
    () => writtenChapters(novel.data ?? { chapters: [] }).map((c) => ({ title: c.title, html: chapterHtml(c.text!) })),
    [novel.data],
  );

  useEffect(() => {
    if (novel.data?.title) document.title = t("print.documentTitle", { name: novel.data.title });
  }, [novel.data?.title, t]);

  if (novel.error) {
    return (
      <p role="alert" className="notice error">
        {t("novel.loadFailed", { error: novel.error.message })}
      </p>
    );
  }
  if (!novel.data) return <div className={mapStyles.loading}>{t("novel.loading")}</div>;
  const n = novel.data;

  return (
    <div className={styles.page} lang={n.language}>
      <div className={mapStyles.toolbar}>
        <Link to={`/novels/${encodeURIComponent(id)}`} className={mapStyles.back}>
          {t("novelPrint.back")}
        </Link>
        <button type="button" className={mapStyles.printBtn} onClick={() => window.print()}>
          {t("print.print")}
        </button>
      </div>

      <section data-part="title" className={styles.titlePage}>
        <h1>{n.title}</h1>
        <p className={styles.byline}>{novelByline(n, t, language)}</p>
      </section>

      {chapters.map((chapter, i) => (
        <section key={i} data-part="chapter" className={styles.chapter}>
          <h2>{chapter.title}</h2>
          <div className={styles.text} dangerouslySetInnerHTML={{ __html: chapter.html }} />
        </section>
      ))}
    </div>
  );
}
