// Preferences' Owner token (DEL-154, audit finding 9): the install's owner's alone. The owner token never expires, so
// the owner can make a new one here at once, as `delve token --new` does: the old one and every link that carried it
// stop working, without a restart. The new links are shown once, until Done; the server never shows them again.
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useConfirm } from "../components/dialogs";
import { useT } from "../i18n";
import { newOwnerToken, type NewOwnerToken } from "../token";

export default function OwnerToken() {
  const t = useT();
  const confirm = useConfirm();
  const [made, setMade] = useState<NewOwnerToken | null>(null);
  const make = useMutation({ mutationFn: newOwnerToken, onSuccess: setMade });

  return (
    <section className="owner-token" aria-labelledby="owner-token-title">
      <h2 id="owner-token-title">{t("ownerToken.title")}</h2>
      <p className="lede">{t("ownerToken.intro")}</p>
      <button
        type="button"
        disabled={make.isPending}
        onClick={async () => {
          const sure = await confirm({
            title: t("ownerToken.confirm"),
            body: t("ownerToken.confirmBody"),
            confirm: t("dialog.make"),
            danger: true,
          });
          if (sure) make.mutate();
        }}
      >
        {make.isPending ? t("ownerToken.making") : t("ownerToken.make")}
      </button>
      {make.error && (
        <p role="alert" className="notice error">
          {t("ownerToken.failed", { error: make.error.message })}
        </p>
      )}
      {made && (
        <div className="notice owner-token-links" role="status">
          <p>{t("ownerToken.made")}</p>
          <ul>
            {made.links.map((link) => (
              <li key={link}>
                <code>{link}</code>
              </li>
            ))}
          </ul>
          <p className="hint">{t("ownerToken.once")}</p>
          <button type="button" onClick={() => setMade(null)}>
            {t("ownerToken.done")}
          </button>
        </div>
      )}
    </section>
  );
}
