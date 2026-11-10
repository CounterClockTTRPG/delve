import { useEffect, useState } from "react";
import { useT } from "../i18n";
import type { HotseatPlayer, PartyMember, PlaySettings, TableSettings } from "./api";

/**
 * The host's Hotseat (DEL-365), in the host's options: a switch for several players at this screen, and while it is
 * on, the players by name with the characters each plays. Only characters this screen plays can be given out (its own,
 * and those nobody at the table has claimed), one player each. Every change is sent at once, the whole list.
 */
export default function HotseatSetup({
  settings,
  party,
  free,
  busy,
  onChange,
}: {
  /** The table options as the server has them; undefined while they load. */
  settings: Pick<PlaySettings, "hotseat" | "hotseat_players"> | undefined;
  party: PartyMember[];
  /** The characters this screen plays, which may be given to a hotseat player. */
  free: Set<string>;
  busy: boolean;
  onChange: (patch: Partial<Pick<TableSettings, "hotseat" | "hotseat_players">>) => void;
}) {
  const t = useT();
  const on = settings?.hotseat ?? false;
  const players = settings?.hotseat_players ?? [];
  const offered = party.filter((m) => free.has(m.id));
  const [adding, setAdding] = useState("");

  const save = (next: HotseatPlayer[]) => onChange({ hotseat_players: next });
  const toggle = (index: number, characterId: string) =>
    save(
      players.map((p, i) => {
        if (i === index) {
          const has = p.characters.includes(characterId);
          return { ...p, characters: has ? p.characters.filter((id) => id !== characterId) : [...p.characters, characterId] };
        }
        // One player plays each character: ticking it for one takes it from the other.
        return { ...p, characters: p.characters.filter((id) => id !== characterId) };
      }),
    );

  function add() {
    const name = adding.trim();
    if (!name) return;
    save([...players, { name, characters: [] }]);
    setAdding("");
  }

  return (
    <div className="hotseat-setup" data-testid="hotseat-setup">
      <h3>{t("play.hotseat")}</h3>
      <label className="hotseat-switch">
        <input
          type="checkbox"
          data-testid="hotseat-on"
          checked={on}
          disabled={!settings || busy}
          onChange={(e) => onChange({ hotseat: e.target.checked })}
        />
        {t("play.hotseatOn")}
      </label>
      <p className="hint">{t("play.hotseatHint")}</p>
      {on && (
        <>
          {players.length === 0 && <p className="hint">{t("play.hotseatNone")}</p>}
          <ul className="hotseat-players">
            {players.map((player, index) => (
              <li key={player.id ?? `new-${index}`} data-testid="hotseat-player">
                <PlayerName
                  name={player.name}
                  disabled={busy}
                  onRename={(name) => save(players.map((p, i) => (i === index ? { ...p, name } : p)))}
                />
                <fieldset className="hotseat-characters">
                  <legend className="visually-hidden">{t("play.hotseatPlays", { name: player.name })}</legend>
                  {offered.map((member) => (
                    <label key={member.id}>
                      <input
                        type="checkbox"
                        checked={player.characters.includes(member.id)}
                        disabled={busy}
                        onChange={() => toggle(index, member.id)}
                      />
                      {member.name}
                    </label>
                  ))}
                </fieldset>
                <button
                  type="button"
                  className="link-button danger"
                  disabled={busy}
                  onClick={() => save(players.filter((_, i) => i !== index))}
                >
                  {t("play.hotseatRemove", { name: player.name })}
                </button>
              </li>
            ))}
          </ul>
          <form
            className="hotseat-add"
            onSubmit={(e) => {
              e.preventDefault();
              add();
            }}
          >
            <input
              aria-label={t("play.hotseatName")}
              placeholder={t("play.hotseatName")}
              data-testid="hotseat-name"
              maxLength={40}
              value={adding}
              onChange={(e) => setAdding(e.target.value)}
            />
            <button type="submit" disabled={busy || !adding.trim()}>
              {t("play.hotseatAdd")}
            </button>
          </form>
          {offered.length < party.length && <p className="hint">{t("play.hotseatFree")}</p>}
        </>
      )}
    </div>
  );
}

/** A player's name, sent when the box loses focus or Enter is pressed, and only when it changed. */
function PlayerName({ name, disabled, onRename }: { name: string; disabled: boolean; onRename: (name: string) => void }) {
  const t = useT();
  const [value, setValue] = useState(name);
  useEffect(() => setValue(name), [name]);
  const done = () => {
    const next = value.trim();
    if (next && next !== name) onRename(next);
    else setValue(name);
  };
  return (
    <input
      className="hotseat-name"
      aria-label={t("play.hotseatName")}
      maxLength={40}
      value={value}
      disabled={disabled}
      onChange={(e) => setValue(e.target.value)}
      onBlur={done}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          done();
        }
      }}
    />
  );
}
