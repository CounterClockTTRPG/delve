import { useT } from "../i18n";

/** Says the campaign's ruleset or setting isn't installed, in place of the composer, which can't act without it. */
export default function MissingPack({ kind, id }: { kind: "ruleset" | "setting"; id: string }) {
  const t = useT();
  return (
    <p className="notice error" role="alert" data-testid="missing-pack">
      {t(kind === "ruleset" ? "play.missingRuleset" : "play.missingSetting", { id })}
    </p>
  );
}
