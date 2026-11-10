import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useT } from "../i18n";
import { classTerms, term } from "../i18n/terms";
import { getPregens, playKeys } from "./api";

/**
 * The module's pregenerated characters, offered to the host while the party is empty (faithful modules Task 19): a
 * checkbox per pregen, none ticked (DEL-187: all twenty were, so one click made them all), and "Ask the DM to make
 * them", which acts for the host: the DM makes the ticked ones in a beat, with `module_pregens` and
 * `create_character`, as the line under the button says. While the table can't act (`blocked`: the session hasn't
 * started) the button waits and says why. Nothing shows when the module has none, or the seat may not read them.
 */
export default function PregenPicker({
  campaignId,
  onAct,
  busy = false,
  blocked = null,
}: {
  campaignId: string;
  /** Submits the host's act with this text. */
  onAct: (text: string) => void;
  busy?: boolean;
  /** Why the table can't act now; the button waits. */
  blocked?: string | null;
}) {
  const t = useT();
  const pregens = useQuery({ queryKey: playKeys.pregens(campaignId), queryFn: () => getPregens(campaignId) });
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const listed = pregens.data?.pregens ?? [];
  if (listed.length === 0) return null;
  const chosen = listed.filter((p) => ticked.has(p.id));

  function toggle(id: string) {
    setTicked((was) => {
      const next = new Set(was);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  return (
    <fieldset className="pregen-picker">
      <legend>{t("play.pregens")}</legend>
      <ul>
        {listed.map((p) => (
          <li key={p.id}>
            <label className="check">
              <input type="checkbox" checked={ticked.has(p.id)} onChange={() => toggle(p.id)} /> {p.name}
            </label>{" "}
            <span className="hint">
              {t("play.pregenSummary", {
                race: term(t, "race", p.race ?? ""),
                class: classTerms(t, p.class ?? ""),
                level: String(p.level ?? ""),
              })}
            </span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        disabled={busy || chosen.length === 0 || blocked !== null}
        aria-describedby="pregens-how"
        onClick={() => onAct(t("play.pregensAct", { names: chosen.map((p) => p.name).join(", ") }))}
      >
        {t("play.pregensMake")}
      </button>
      <p id="pregens-how" className="hint">
        {blocked ?? t(chosen.length === 0 ? "play.pregensPick" : "play.pregensBeat")}
      </p>
    </fieldset>
  );
}
