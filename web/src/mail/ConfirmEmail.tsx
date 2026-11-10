import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { browserLanguage } from "../account/SetPassword";
import { ApiError } from "../api";
import { I18nProvider, useT } from "../i18n";
import { confirmEmail } from "./api";
import "../account/account.css";

/** `/account/email/:token` on its own, outside the app, as `/account/link/:token`: the link is all it needs. */
export function ConfirmEmailRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={browserLanguage()}>
        <ConfirmEmail />
      </I18nProvider>
    </QueryClientProvider>
  );
}

/**
 * The link a confirmation email brought (DEL-314). The address is confirmed on the press of a button, not on
 * opening the page, so a mail program that opens links to check them confirms nothing.
 */
export default function ConfirmEmail() {
  const t = useT();
  const { token = "" } = useParams();
  const confirm = useMutation({ mutationFn: () => confirmEmail(token) });
  const gone = confirm.error instanceof ApiError && confirm.error.status === 404;
  return (
    <main className="gate account-page">
      <div className="gate-card account-form">
        <h1>{t("confirmEmail.title")}</h1>
        {confirm.isSuccess ? (
          <>
            <p role="status">{t("confirmEmail.done")}</p>
            <Link to="/home">{t("confirmEmail.open")}</Link>
          </>
        ) : (
          <>
            <p>{t("confirmEmail.explain")}</p>
            {confirm.error && (
              <p className="notice error" role="alert">
                {gone ? t("confirmEmail.gone") : confirm.error.message}
              </p>
            )}
            <button type="button" className="primary" disabled={confirm.isPending} onClick={() => confirm.mutate()}>
              {t("confirmEmail.submit")}
            </button>
          </>
        )}
      </div>
    </main>
  );
}
