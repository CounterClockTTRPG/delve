import { useT } from "../i18n";

/** Says the campaign's ruleset or setting isn't installed, in place of the composer, which can't act without it; or
 * that its ruleset is installed but only a reference, which no campaign plays (`reference`, DEL-384). */
export default function MissingPack({
  kind,
  id,
  reference = false,
}: {
  kind: "ruleset" | "setting";
  id: string;
  reference?: boolean;
}) {
  const t = useT();
  const key = reference ? "play.referenceRuleset" : kind === "ruleset" ? "play.missingRuleset" : "play.missingSetting";
  return (
    <p className="notice error" role="alert" data-testid="missing-pack">
      {t(key, { id })}
    </p>
  );
}
