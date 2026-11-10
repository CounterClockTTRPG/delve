import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { acceptRequest, accountKeys, declineRequest, getTableRequests, sendRequestMessage, type JoinRequest } from "../account/api";
import RequestThread from "../account/RequestThread";
import { useT } from "../i18n";
import PersonLink from "../profile/PersonLink";
import { playKeys } from "./api";

/**
 * The host's and co-hosts' "Requests to join" (DEL-204), in Host controls: each account waiting to join this public
 * table, with its avatar (a seatless account's profile card isn't the hosts' to open), its note and the thread, a
 * reply box, Accept (a player's seat, while there is a place) and Decline (with a reason for them, if given). Read again on each `join_requests` event; nothing while none waits.
 */
export default function JoinRequests({ campaignId, full }: { campaignId: string; full: boolean }) {
  const t = useT();
  const client = useQueryClient();
  const requests = useQuery({ queryKey: accountKeys.tableRequests(campaignId), queryFn: () => getTableRequests(campaignId) });
  const changed = () => {
    client.invalidateQueries({ queryKey: accountKeys.tableRequests(campaignId) });
    client.invalidateQueries({ queryKey: playKeys.seats(campaignId) });
    client.invalidateQueries({ queryKey: playKeys.listing(campaignId) });
  };
  const send = useMutation({ mutationFn: ({ id, text }: { id: string; text: string }) => sendRequestMessage(id, text), onSuccess: changed });
  const accept = useMutation({ mutationFn: (id: string) => acceptRequest(campaignId, id), onSettled: changed });
  const decline = useMutation({ mutationFn: ({ id, reason }: { id: string; reason: string }) => declineRequest(campaignId, id, reason), onSettled: changed });
  const waiting = (requests.data ?? []).filter((r) => r.status === "pending");
  if (waiting.length === 0) return null;
  const error = send.error ?? accept.error ?? decline.error;
  return (
    <section className="join-requests" data-testid="join-requests" aria-labelledby="join-requests-title">
      <h3 id="join-requests-title">{t("requests.toJoin", { n: String(waiting.length) })}</h3>
      {full && <p className="hint">{t("requests.fullHint")}</p>}
      <ul>
        {waiting.map((request) => (
          <li key={request.id}>
            <div className="join-request-who">
              <PersonLink profile={request.account.profile} name={request.account.display_name} size={28}>
                <strong>{request.account.display_name}</strong>
              </PersonLink>
              {request.role === "observer" && (
                <span className="row-meta" data-testid={`wants-to-watch-${request.id}`}>
                  {t("requests.toWatch")}
                </span>
              )}
            </div>
            <RequestThread
              request={request}
              sending={send.isPending}
              onSend={(text) => send.mutate({ id: request.id, text })}
              actions={
                <Decide
                  request={request}
                  full={full && request.role !== "observer"}
                  busy={accept.isPending || decline.isPending}
                  onAccept={() => accept.mutate(request.id)}
                  onDecline={(reason) => decline.mutate({ id: request.id, reason })}
                />
              }
            />
          </li>
        ))}
      </ul>
      {error && (
        <p className="notice error" role="alert">
          {error.message}
        </p>
      )}
    </section>
  );
}

function Decide({
  request,
  full,
  busy,
  onAccept,
  onDecline,
}: {
  request: JoinRequest;
  full: boolean;
  busy: boolean;
  onAccept: () => void;
  onDecline: (reason: string) => void;
}) {
  const t = useT();
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  if (declining) {
    return (
      <span className="request-decline">
        <label className="visually-hidden" htmlFor={`decline-${request.id}`}>
          {t("requests.reason")}
        </label>
        <input
          id={`decline-${request.id}`}
          value={reason}
          placeholder={t("requests.reasonPlaceholder")}
          onChange={(e) => setReason(e.target.value)}
        />
        <button type="button" className="danger" data-testid={`decline-confirm-${request.id}`} disabled={busy}
          onClick={() => onDecline(reason.trim())}>
          {t("requests.decline")}
        </button>
        <button type="button" onClick={() => setDeclining(false)}>
          {t("dialog.cancel")}
        </button>
      </span>
    );
  }
  return (
    <>
      <button type="button" className="primary" data-testid={`accept-${request.id}`} disabled={busy || full} onClick={onAccept}>
        {t("requests.accept")}
      </button>
      <button type="button" data-testid={`decline-${request.id}`} disabled={busy} onClick={() => setDeclining(true)}>
        {t("requests.decline")}
      </button>
    </>
  );
}
