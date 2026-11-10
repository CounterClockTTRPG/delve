import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useT } from "../i18n";
import {
  accountEmailKey,
  askToConfirm,
  getAccountEmail,
  removeEmail,
  setMailSwitches,
  useMailEnabled,
  type AccountEmail,
  type MailSwitches,
} from "./api";
import "../account/account.css";

/**
 * Preferences' Email section (DEL-314): the account's own address, which only it sees; a new one waits for the
 * link sent to it ("Send the link again"), and the one in use stays until then; the switches for a host's mail and
 * the board's. The field shows only while Delve sends mail, as confirming needs an email; an address Google gave is
 * shown either way, with Remove.
 */
export default function EmailSection() {
  const t = useT();
  const client = useQueryClient();
  const enabled = useMailEnabled();
  const current = useQuery({ queryKey: accountEmailKey, queryFn: getAccountEmail });
  const [address, setAddress] = useState("");
  const [status, setStatus] = useState<{ kind: "idle" } | { kind: "sent" } | { kind: "error"; message: string }>({ kind: "idle" });
  const saved = (answer: AccountEmail) => client.setQueryData(accountEmailKey, answer);
  const send = useMutation({
    mutationFn: askToConfirm,
    onSuccess: (answer) => {
      saved(answer);
      setAddress("");
      setStatus({ kind: "sent" });
    },
    onError: (error) => setStatus({ kind: "error", message: error.message }),
  });
  const remove = useMutation({
    mutationFn: removeEmail,
    onSuccess: () => {
      setStatus({ kind: "idle" });
      client.invalidateQueries({ queryKey: accountEmailKey });
    },
    onError: (error) => setStatus({ kind: "error", message: error.message }),
  });
  const switches = useMutation({
    mutationFn: (change: MailSwitches) => setMailSwitches(change),
    onSuccess: saved,
    onError: (error) => setStatus({ kind: "error", message: error.message }),
  });

  const data = current.data;
  if (!data || (!enabled && !data.email && !data.pending)) return null;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (send.isPending || !address.trim()) return;
    setStatus({ kind: "idle" });
    send.mutate(address.trim());
  }

  return (
    <section className="account-section" aria-labelledby="email-title">
      <h2 id="email-title">{t("accountEmail.title")}</h2>
      <p className="hint">{t("accountEmail.explain")}</p>
      {data.email ? (
        <p data-testid="email-current">
          {t("accountEmail.current", { address: data.email })}{" "}
          <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}>
            {t("accountEmail.remove")}
          </button>
        </p>
      ) : (
        !data.pending && <p data-testid="email-current">{t("accountEmail.none")}</p>
      )}
      {data.pending && (
        <p data-testid="email-pending">
          {t("accountEmail.pending", { address: data.pending })}{" "}
          {enabled && (
            <button type="button" disabled={send.isPending} onClick={() => send.mutate(data.pending ?? "")}>
              {t("accountEmail.again")}
            </button>
          )}
          {!data.email && (
            <button type="button" disabled={remove.isPending} onClick={() => remove.mutate()}>
              {t("accountEmail.cancel")}
            </button>
          )}
        </p>
      )}
      {enabled && (
        <form className="account-form" onSubmit={submit}>
          <label htmlFor="email-address">{t(data.email ? "accountEmail.change" : "accountEmail.address")}</label>
          <input
            id="email-address"
            data-testid="email-address"
            type="email"
            value={address}
            autoComplete="email"
            maxLength={254}
            onChange={(e) => setAddress(e.target.value)}
          />
          <button type="submit" data-testid="email-send" disabled={send.isPending}>
            {t("accountEmail.send")}
          </button>
        </form>
      )}
      {status.kind === "error" && (
        <p className="notice error" role="alert">
          {status.message}
        </p>
      )}
      <span role="status" className="status">
        {status.kind === "sent" && t("accountEmail.sent")}
      </span>
      {enabled && data.email && (
        <fieldset className="email-switches">
          <legend>{t("accountEmail.switches")}</legend>
          <label className="check">
            <input
              type="checkbox"
              checked={data.mail_host}
              disabled={switches.isPending}
              onChange={(e) => switches.mutate({ mail_host: e.target.checked })}
            />
            {t("accountEmail.mailHost")}
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={data.mail_board}
              disabled={switches.isPending}
              onChange={(e) => switches.mutate({ mail_board: e.target.checked })}
            />
            {t("accountEmail.mailBoard")}
          </label>
        </fieldset>
      )}
    </section>
  );
}
