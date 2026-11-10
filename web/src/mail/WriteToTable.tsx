import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { apiFetch, postJson } from "../api";
import { useT } from "../i18n";
import type { Seat } from "../play/api";
import { useMailEnabled } from "./api";

export const SUBJECT_LIMIT = 120;
export const MESSAGE_LIMIT = 5000;

interface TableMail {
  subject: string;
  message: string;
  seats?: string[];
  reply_to_me: boolean;
}

const mailPath = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}/mail`;
/** How many a message to the whole table would reach by email now (never counted for chosen seats: that would say
 * who has an address). */
const getMailCount = (campaignId: string) => apiFetch<{ count: number }>(`${mailPath(campaignId)}/count`);
/** How many it went to for the whole table; null for chosen seats. */
const writeToTable = (campaignId: string, mail: TableMail) => postJson<{ sent: number | null }>(mailPath(campaignId), mail);

/**
 * The host's and co-hosts' message to the table by email (DEL-314), in Host controls: a subject and a message to
 * everyone at the table or the players ticked (never observers), and whether a reply reaches the host's own address.
 * Delve sends it, one email each, and no one sees another's address; for the whole table it says how many will get it,
 * never for ticked players (that would tell who has an address). Nothing while Delve sends no mail.
 */
export default function WriteToTable({ campaignId, seats, mySeatId }: { campaignId: string; seats: Seat[]; mySeatId: string }) {
  const t = useT();
  const mail = useMailEnabled();
  const [open, setOpen] = useState(false);
  // undefined: nothing sent yet; null: sent to ticked players, no number.
  const [sentTo, setSentTo] = useState<number | null | undefined>(undefined);
  if (!mail) return null;
  return (
    <div className="write-to-table">
      <button type="button" data-testid="write-to-table" onClick={() => (setSentTo(undefined), setOpen(true))}>
        {t("mail.write.open")}
      </button>
      {sentTo !== undefined && (
        <p className="notice" role="status" data-testid="write-sent">
          {sentTo === null ? t("mail.write.sentSome") : t("mail.write.sent", { count: String(sentTo) })}
        </p>
      )}
      {open && (
        <WriteDialog
          campaignId={campaignId}
          seats={seats.filter((s) => s.id !== mySeatId && s.role !== "observer")}
          onClose={() => setOpen(false)}
          onSent={(count) => (setSentTo(count), setOpen(false))}
        />
      )}
    </div>
  );
}

function WriteDialog({
  campaignId,
  seats,
  onClose,
  onSent,
}: {
  campaignId: string;
  seats: Seat[];
  onClose: () => void;
  onSent: (count: number | null) => void;
}) {
  const t = useT();
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [everyone, setEveryone] = useState(true);
  const [ticked, setTicked] = useState<string[]>([]);
  const [replyToMe, setReplyToMe] = useState(false);
  // Ticked in the table's order, whatever order they were ticked in.
  const chosen = everyone ? null : seats.filter((s) => ticked.includes(s.id)).map((s) => s.id);
  const count = useQuery({ queryKey: ["mail", "count", campaignId], queryFn: () => getMailCount(campaignId) });
  const send = useMutation({
    mutationFn: () =>
      writeToTable(campaignId, {
        subject: subject.trim(),
        message,
        ...(chosen ? { seats: chosen } : {}),
        reply_to_me: replyToMe,
      }),
    onSuccess: (answer) => onSent(answer.sent),
  });
  const ready = subject.trim() !== "" && message.trim() !== "" && (chosen === null || chosen.length > 0);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ready) send.mutate();
  }

  const toggle = (id: string) => setTicked((now) => (now.includes(id) ? now.filter((x) => x !== id) : [...now, id]));

  return (
    <Dialog.Root open onOpenChange={(isOpen) => isOpen || onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog write-dialog">
          <Dialog.Title className="dialog-title">{t("mail.write.title")}</Dialog.Title>
          <Dialog.Description className="dialog-body">{t("mail.write.lede")}</Dialog.Description>
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="write-subject">{t("mail.write.subject")}</label>
              <input id="write-subject" value={subject} maxLength={SUBJECT_LIMIT} autoComplete="off"
                onChange={(e) => setSubject(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="write-message">{t("mail.write.message")}</label>
              <textarea id="write-message" rows={6} value={message} maxLength={MESSAGE_LIMIT}
                onChange={(e) => setMessage(e.target.value)} />
            </div>
            <fieldset className="write-who">
              <legend>{t("mail.write.who")}</legend>
              <label className="check">
                <input type="radio" name="write-who" checked={everyone} onChange={() => setEveryone(true)} />
                {t("mail.write.everyone")}
              </label>
              <label className="check">
                <input type="radio" name="write-who" checked={!everyone} onChange={() => setEveryone(false)} />
                {t("mail.write.some")}
              </label>
              {!everyone && (
                <ul className="write-seats">
                  {seats.map((s) => (
                    <li key={s.id}>
                      <label className="check">
                        <input type="checkbox" checked={ticked.includes(s.id)} onChange={() => toggle(s.id)} />
                        {s.name}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
            <label className="check write-reply">
              <input type="checkbox" checked={replyToMe} onChange={(e) => setReplyToMe(e.target.checked)} />
              {t("mail.write.replyToMe")}
            </label>
            {everyone && count.data && (
              <p className="hint" data-testid="write-count">
                {t("mail.write.count", { count: String(count.data.count) })}
              </p>
            )}
            {send.error && (
              <p className="notice error" role="alert">
                {send.error.message}
              </p>
            )}
            <div className="dialog-actions">
              <Dialog.Close asChild>
                <button type="button">{t("dialog.cancel")}</button>
              </Dialog.Close>
              <button type="submit" className="primary" disabled={!ready || send.isPending}>
                {t("mail.write.send")}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
