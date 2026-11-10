import { useEffect } from "react";
import { useRouteError } from "react-router-dom";
import { useT } from "./i18n";
import { isStaleBuild, reloadForNewBuild } from "./staleBuild";

/**
 * What a screen shows when it fails to render: after a deploy, a screen whose code the new build replaced reloads the
 * page once (`staleBuild.ts`); anything else says what went wrong, with Reload.
 */
export default function AppError() {
  const t = useT();
  const error = useRouteError();
  const stale = isStaleBuild(error);
  useEffect(() => {
    if (stale) reloadForNewBuild();
  }, [stale]);
  const message = error instanceof Error ? error.message : String(error ?? "");
  return (
    <section className="page app-error" role="alert">
      <h1>{t(stale ? "appError.updated" : "appError.title")}</h1>
      <p>{t(stale ? "appError.updatedText" : "appError.text")}</p>
      {!stale && message && <pre className="app-error-detail">{message}</pre>}
      <button type="button" className="primary" onClick={() => window.location.reload()}>
        {t("appError.reload")}
      </button>
    </section>
  );
}
