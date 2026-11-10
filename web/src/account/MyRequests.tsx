import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useT } from "../i18n";
import RequestThread from "./RequestThread";
import { accountKeys, getMyRequests, sendRequestMessage, withdrawRequest, type JoinRequest } from "./api";

/** How often a player's requests are read again: a player without a seat at the table hears none of its events. */
const EVERY_MS = 30_000;

/**
 * My tables' "Your requests" (DEL-204): the account's requests to join public tables, newest first, each with where it
 * stands and its thread with the hosts; while it waits, a reply box and Withdraw. An accepted request opens its table.
 * Read again every half minute and when the page comes back into view. Nothing when the account never asked.
 */
export default function MyRequests() {
  const t = useT();
  const client = useQueryClient();
  const requests = useQuery({
    queryKey: accountKeys.requests,
    queryFn: getMyRequests,
    refetchInterval: EVERY_MS,
    refetchOnWindowFocus: true,
  });
  const refresh = () => {
    client.invalidateQueries({ queryKey: accountKeys.requests });
    client.invalidateQueries({ queryKey: accountKeys.findTables });
    client.invalidateQueries({ queryKey: accountKeys.tables });
  };
  const send = useMutation({ mutationFn: ({ id, text }: { id: string; text: string }) => sendRequestMessage(id, text), onSuccess: refresh });
  const withdraw = useMutation({ mutationFn: (id: string) => withdrawRequest(id), onSuccess: refresh });
  if (!requests.data || requests.data.length === 0) return null;
  return (
    <section className="my-requests" data-testid="my-requests">
      <h2>{t("requests.yours")}</h2>
      <ul>
        {requests.data.map((request) => (
          <li key={request.id} className="my-request">
            <div className="my-request-head">
              <strong>{request.campaign?.name ?? ""}</strong>
              {request.campaign?.module_title && <span className="row-meta">{request.campaign.module_title}</span>}
              <span className={`request-status ${request.status}`}>{t(`requests.status.${request.status}`)}</span>
              {request.status === "accepted" && (
                <Link className="button-like primary" to={`/play/${encodeURIComponent(request.campaign_id)}`}>
                  {t("tables.play")}
                </Link>
              )}
            </div>
            <RequestThread
              request={request}
              sending={send.isPending}
              onSend={(text) => send.mutate({ id: request.id, text })}
              actions={<Withdraw request={request} busy={withdraw.isPending} onWithdraw={() => withdraw.mutate(request.id)} />}
            />
          </li>
        ))}
      </ul>
      {(send.error ?? withdraw.error) && (
        <p className="notice error" role="alert">
          {(send.error ?? withdraw.error)?.message}
        </p>
      )}
    </section>
  );
}

function Withdraw({ request, busy, onWithdraw }: { request: JoinRequest; busy: boolean; onWithdraw: () => void }) {
  const t = useT();
  if (request.status !== "pending") return null;
  return (
    <button type="button" disabled={busy} onClick={onWithdraw}>
      {t("requests.withdraw")}
    </button>
  );
}
