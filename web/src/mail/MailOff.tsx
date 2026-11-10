import { QueryClient, QueryClientProvider, useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { browserLanguage } from "../account/SetPassword";
import { ApiError } from "../api";
import { I18nProvider, useT } from "../i18n";
import { getOffLink, turnMailOff } from "./api";
import "../account/account.css";

/** `/mail/off/:token` on its own, outside the app: an email's off link, no login needed. */
export function MailOffRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <I18nProvider language={browserLanguage()}>
        <MailOff />
      </I18nProvider>
    </QueryClientProvider>
  );
}

/**
 * Turns one kind of mail off (DEL-314): a host's mail, or the board's replies, as the link says. It asks first, so a
 * mail program that opens links to check them turns nothing off; Preferences turns it back on.
 */
export default function MailOff() {
  const t = useT();
  const { token = "" } = useParams();
  const link = useQuery({ queryKey: ["mail", "off", token], queryFn: () => getOffLink(token) });
  const off = useMutation({ mutationFn: () => turnMailOff(token) });
  const refusal = link.error ?? off.error;
  const group = link.data?.group;
  return (
    <main className="gate account-page">
      <div className="gate-card account-form">
        <h1>{t("mailOff.title")}</h1>
        {link.isPending && <p className="placeholder">{t("preferences.loading")}</p>}
        {refusal && (
          <p className="notice error" role="alert">
            {refusal instanceof ApiError && refusal.status === 404 ? t("mailOff.gone") : refusal.message}
          </p>
        )}
        {group &&
          (off.isSuccess ? (
            <p role="status">{t(`mailOff.done.${group}`)}</p>
          ) : (
            <>
              <p>{t(`mailOff.ask.${group}`)}</p>
              <button type="button" className="primary" disabled={off.isPending} onClick={() => off.mutate()}>
                {t("mailOff.submit")}
              </button>
            </>
          ))}
      </div>
    </main>
  );
}
