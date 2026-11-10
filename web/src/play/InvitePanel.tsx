import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import { copyText } from "../components/copyText";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { getInvite, newInvite, playKeys, type Invite } from "./api";

const LOOPBACK_HOSTS = new Set(["localhost", "[::1]", "::1"]);

/** The join link to show: at the address the host's browser is on, unless that is loopback, which no other device
 * reaches; then the server's (its first LAN address), and `loopback` says so. */
export function inviteUrl(invite: Invite, here: URL | Location): { url: string; loopback: boolean } {
  const host = here.hostname.toLowerCase();
  if (LOOPBACK_HOSTS.has(host) || host.startsWith("127.")) return { url: invite.url, loopback: true };
  return { url: `${here.origin}/join/${encodeURIComponent(invite.join_token)}`, loopback: false };
}

/**
 * The invite, for the host: the join link with a copy button, its QR code drawn on a canvas, and "New link", after
 * which the old link stops working (spec §7.2). On loopback it says that other devices need the LAN address.
 */
export default function InvitePanel({ campaignId }: { campaignId: string }) {
  const t = useT();
  const confirm = useConfirm();
  const client = useQueryClient();
  const canvas = useRef<HTMLCanvasElement>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  const invite = useQuery({ queryKey: playKeys.invite(campaignId), queryFn: () => getInvite(campaignId) });
  const renew = useMutation({
    mutationFn: () => newInvite(campaignId),
    onSuccess: (fresh) => client.setQueryData(playKeys.invite(campaignId), fresh),
  });
  const shown = invite.data ? inviteUrl(invite.data, window.location) : null;
  const url = shown?.url;

  useEffect(() => {
    setCopied(null);
    if (url && canvas.current) void QRCode.toCanvas(canvas.current, url, { margin: 1, width: 176 }).catch(() => {});
  }, [url]);

  async function copy() {
    if (!url) return;
    setCopied(await copyText(url));
  }

  async function renewLink() {
    const sure = await confirm({ title: t("play.newLinkTitle"), body: t("play.newLinkBody"), confirm: t("play.newLinkConfirm") });
    if (sure) renew.mutate();
  }

  const error = invite.error ?? renew.error;
  return (
    <section className="invite-panel" data-testid="invite-panel" aria-label={t("play.invite")}>
      <label htmlFor="invite-url">{t("play.inviteLink")}</label>
      <div className="invite-link">
        <input id="invite-url" data-testid="invite-url" readOnly value={url ?? ""} onFocus={(e) => e.target.select()} />
        <button type="button" onClick={() => void copy()} disabled={!url}>
          {t("play.copy")}
        </button>
      </div>
      <p className="hint">{t("invite.accountHint")}</p>
      {shown?.loopback && (
        <p className="hint" data-testid="invite-loopback">
          {t("play.inviteLoopback")}
        </p>
      )}
      {copied !== null && (
        <p className="hint" role="status">
          {t(copied ? "play.copied" : "play.copyFailed")}
        </p>
      )}
      <canvas ref={canvas} className="invite-qr" data-testid="invite-qr" role="img" aria-label={t("play.qr")} />
      <button type="button" onClick={() => void renewLink()} disabled={renew.isPending}>
        {t("play.newLink")}
      </button>
      {error && (
        <p className="notice error" role="alert">
          {error.message}
        </p>
      )}
    </section>
  );
}
