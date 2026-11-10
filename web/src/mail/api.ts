// Whether Delve sends email (DEL-314): the server's yes or no, open to anyone, so a page offers an address field only
// when a confirmation could reach it.
import { useQuery } from "@tanstack/react-query";
import { apiFetch, deleteJson, postJson, putJson } from "../api";

export interface MailStatus {
  enabled: boolean;
}

export const mailStatusKey = ["mail", "status"];

export const getMailStatus = () => apiFetch<MailStatus>("/api/mail/status");

/** Whether email goes; false until the answer comes (or when it fails). */
export function useMailEnabled(): boolean {
  const status = useQuery({ queryKey: mailStatusKey, queryFn: getMailStatus, retry: false, staleTime: 60_000 });
  return status.data?.enabled ?? false;
}

/** The account's own address (DEL-314), the one waiting for its confirmation link, and its mail switches. Only the
 * account itself reads it. */
export interface AccountEmail {
  email: string | null;
  pending: string | null;
  mail_host: boolean;
  mail_board: boolean;
}

export type MailSwitches = Partial<Pick<AccountEmail, "mail_host" | "mail_board">>;

export type MailGroup = "host" | "board";

export const accountEmailKey = ["account", "email"];

export const getAccountEmail = () => apiFetch<AccountEmail>("/api/account/email");
/** Make `address` the one to confirm, and send its link (again). */
export const askToConfirm = (address: string) => putJson<AccountEmail>("/api/account/email", { address });
export const removeEmail = () => deleteJson("/api/account/email");
export const setMailSwitches = (switches: MailSwitches) => putJson<AccountEmail>("/api/account/mail", switches);
export const confirmEmail = (token: string) => postJson<{ confirmed: boolean }>("/api/account/email/confirm", { token });

const offPath = (token: string) => `/api/mail/off/${encodeURIComponent(token)}`;
export const getOffLink = (token: string) => apiFetch<{ group: MailGroup }>(offPath(token));
export const turnMailOff = (token: string) => postJson<{ group: MailGroup }>(offPath(token));
