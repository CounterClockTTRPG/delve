import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useT } from "../i18n";
import { accountKeys, getMe, keepSeat } from "./api";
import "./account.css";

/**
 * Above the play screen, for an account whose browser still has a seat token at this table from before accounts
 * (players and tavern Task E3): Keep this seat makes that seat the account's, so it finds it again on any device.
 */
export default function KeepSeat({ campaignId }: { campaignId: string }) {
  const t = useT();
  const client = useQueryClient();
  const me = useQuery({ queryKey: accountKeys.me(campaignId), queryFn: () => getMe(campaignId) });
  const keep = useMutation({
    mutationFn: () => keepSeat(campaignId),
    // Who this browser is at the table changed: the seat is the account's now.
    onSuccess: () => client.invalidateQueries({ queryKey: accountKeys.me() }),
  });
  const seat = me.data?.keepable_seat;
  if (!seat) return null;
  return (
    <div className="notice keep-seat" role="status">
      <span>{t("keepSeat.text", { name: seat.name })}</span>
      <button type="button" data-testid="keep-seat" disabled={keep.isPending} onClick={() => keep.mutate()}>
        {t("keepSeat.keep")}
      </button>
      {keep.error && <span role="alert">{keep.error.message}</span>}
    </div>
  );
}
