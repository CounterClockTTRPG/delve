import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import {
  ApiError,
  NeedsToken,
  getCharactersView,
  getDmView,
  getDoorsAndSecrets,
  getMapState,
  moveCharacters,
  queryKeys,
  revealNode,
  revealSecret,
  setDoor,
  startMapState,
  type TableCharacter,
  type MapStateResponse,
  type NodeCandidate,
} from "../api";
import { SvgPreview } from "../editor/SvgPreview";
import { useT } from "../i18n";

// The door states the DSL knows (as the editor's door tool offers them).
const DOOR_STATES = ["closed", "open", "locked"];

type Tab = "characters" | "dm";
type NodeAction = "move" | "reveal";

/**
 * The host's tool for one map state of a campaign (plateau 1; the play screen is plateau 2).
 * The characters' view and the DM view are two routes; the tab picks which one is asked for,
 * and the characters' tab never asks for the DM view.
 */
export default function MapStatePanel({
  campaignId,
  mapName,
  characters,
}: {
  campaignId: string;
  mapName: string;
  characters: TableCharacter[];
}) {
  const t = useT();
  const client = useQueryClient();
  const key = queryKeys.mapState(campaignId, mapName);
  // null: every character, also those added later.
  const [picked, setPicked] = useState<string[] | null>(null);
  const selected = characters.map((c) => c.id).filter((id) => picked === null || picked.includes(id));
  const [tab, setTab] = useState<Tab>("characters");
  const [node, setNode] = useState("");
  const [revealDoors, setRevealDoors] = useState(true);
  const [door, setDoorKey] = useState("");
  const [doorState, setDoorState] = useState(DOOR_STATES[0]);
  const [secret, setSecret] = useState("");
  // The last node action, kept so a candidate from a 404 can redo it.
  const [candidates, setCandidates] = useState<{ action: NodeAction; nodes: NodeCandidate[] } | null>(null);

  const state = useQuery({ queryKey: [...key, "state"], queryFn: () => getMapState(campaignId, mapName) });
  // The map's doors and secrets to pick from: the DM view's knowledge, on an organiser route like this panel's.
  const listed = useQuery({
    queryKey: [...key, "doors-and-secrets"],
    queryFn: () => getDoorsAndSecrets(campaignId, mapName),
  });
  const doors = listed.data?.doors ?? [];
  const secrets = listed.data?.secrets ?? [];
  const doorKey = door || doors[0]?.key || "";
  const secretKey = secret || secrets[0]?.key || "";
  const charactersView = useQuery({
    queryKey: [...key, "view", selected.join(",")],
    queryFn: () => getCharactersView(campaignId, mapName, selected),
    enabled: tab === "characters" && selected.length > 0,
  });
  const dmView = useQuery({
    queryKey: [...key, "dm-view"],
    queryFn: () => getDmView(campaignId, mapName),
    enabled: tab === "dm",
  });

  const change = useMutation({
    mutationFn: (run: () => Promise<MapStateResponse>) => run(),
    onSuccess: (next) => {
      client.setQueryData([...key, "state"], next);
      client.invalidateQueries({ queryKey: key });
    },
  });

  function toggle(id: string) {
    setPicked(selected.includes(id) ? selected.filter((s) => s !== id) : [...selected, id]);
  }

  function onNode(action: NodeAction, target: string) {
    const to = target.trim();
    if (!to || selected.length === 0) return;
    setCandidates(null);
    const run =
      action === "move"
        ? () => moveCharacters(campaignId, mapName, selected, to)
        : () => revealNode(campaignId, mapName, selected, to, revealDoors);
    change.mutate(run, {
      onError: (error) => {
        if (error instanceof ApiError && error.status === 404 && Array.isArray(error.body.candidates)) {
          setCandidates({ action, nodes: error.body.candidates as NodeCandidate[] });
        }
      },
    });
  }

  function submitNode(e: FormEvent) {
    e.preventDefault();
    onNode("move", node);
  }

  const view = tab === "characters" ? charactersView : dmView;
  const offline = view.error instanceof ApiError && view.error.status === 409;
  const failed = change.error && !(change.error instanceof NeedsToken) && !candidates ? change.error : null;
  const where = state.data?.characters ?? {};

  return (
    <section className="map-state" aria-label={t("mapState.label", { map: mapName })}>
      <fieldset className="map-state-characters">
        <legend>{t("mapState.characters")}</legend>
        {characters.length === 0 ? (
          <p className="placeholder">{t("mapState.noCharacters")}</p>
        ) : (
          characters.map((c) => (
            <label key={c.id} className="check">
              <input type="checkbox" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
              {c.name}
            </label>
          ))
        )}
      </fieldset>

      <div className="map-state-controls">
        <button type="button" disabled={selected.length === 0 || change.isPending} onClick={() => change.mutate(() => startMapState(campaignId, mapName, selected))}>
          {t("mapState.start")}
        </button>

        <form className="inline-form" onSubmit={submitNode}>
          <div className="field">
            <label htmlFor={`${mapName}-node`}>{t("mapState.node")}</label>
            <input
              id={`${mapName}-node`}
              value={node}
              placeholder={t("mapState.nodeHint")}
              onChange={(e) => setNode(e.target.value)}
              spellCheck={false}
            />
          </div>
          <button type="submit" className="primary" disabled={selected.length === 0 || change.isPending}>
            {t("mapState.move")}
          </button>
          <button type="button" disabled={selected.length === 0 || change.isPending} onClick={() => onNode("reveal", node)}>
            {t("mapState.reveal")}
          </button>
          <label className="check">
            <input type="checkbox" checked={revealDoors} onChange={(e) => setRevealDoors(e.target.checked)} />
            {t("mapState.revealDoors")}
          </label>
        </form>

        {candidates && (
          <div role="group" aria-label={t("mapState.didYouMean")} className="notice">
            <p>{t("mapState.unknownNode")}</p>
            <div className="candidates">
              {candidates.nodes.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => {
                    setNode(n.id);
                    onNode(candidates.action, n.id);
                  }}
                >
                  {n.label} ({n.id})
                </button>
              ))}
            </div>
          </div>
        )}

        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (doorKey) change.mutate(() => setDoor(campaignId, mapName, doorKey, doorState));
          }}
        >
          <div className="field">
            <label htmlFor={`${mapName}-door`}>{t("mapState.door")}</label>
            <select id={`${mapName}-door`} value={doorKey} disabled={doors.length === 0} onChange={(e) => setDoorKey(e.target.value)}>
              {doors.length === 0 ? (
                <option value="" disabled>
                  {t("mapState.none")}
                </option>
              ) : (
                doors.map((d) => (
                  <option key={d.key} value={d.key}>
                    {d.key} ({[d.nodes.join(" – "), d.type].join(", ")})
                  </option>
                ))
              )}
            </select>
          </div>
          <div className="field">
            <label htmlFor={`${mapName}-door-state`}>{t("mapState.doorState")}</label>
            <select id={`${mapName}-door-state`} value={doorState} onChange={(e) => setDoorState(e.target.value)}>
              {DOOR_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={!doorKey || change.isPending}>
            {t("mapState.setDoor")}
          </button>
        </form>

        <form
          className="inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (secretKey) change.mutate(() => revealSecret(campaignId, mapName, secretKey));
          }}
        >
          <div className="field">
            <label htmlFor={`${mapName}-secret`}>{t("mapState.secret")}</label>
            <select id={`${mapName}-secret`} value={secretKey} disabled={secrets.length === 0} onChange={(e) => setSecret(e.target.value)}>
              {secrets.length === 0 ? (
                <option value="" disabled>
                  {t("mapState.none")}
                </option>
              ) : (
                secrets.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label} ({s.key})
                  </option>
                ))
              )}
            </select>
          </div>
          <button type="submit" disabled={!secretKey || change.isPending}>
            {t("mapState.revealSecret")}
          </button>
        </form>

        {failed && (
          <p role="alert" className="notice error">
            {t("mapState.failed", { error: failed.message })}
          </p>
        )}
      </div>

      <ul className="positions" aria-label={t("mapState.positions")}>
        {characters.map((c) => (
          <li key={c.id}>
            <span className="position-name">{c.name}</span>
            <span className="position-where">{where[c.id]?.location ?? t("mapState.notHere")}</span>
          </li>
        ))}
      </ul>

      <div role="tablist" className="view-tabs" aria-label={t("mapState.views")}>
        <button
          type="button"
          role="tab"
          id={`${mapName}-tab-characters`}
          aria-selected={tab === "characters"}
          aria-controls={`${mapName}-view`}
          className="view-tab"
          onClick={() => setTab("characters")}
        >
          {t("mapState.charactersView")}
        </button>
        <button
          type="button"
          role="tab"
          id={`${mapName}-tab-dm`}
          aria-selected={tab === "dm"}
          aria-controls={`${mapName}-view`}
          className="view-tab dm"
          onClick={() => setTab("dm")}
        >
          {t("mapState.dmView")}
        </button>
      </div>
      <div
        role="tabpanel"
        id={`${mapName}-view`}
        aria-labelledby={`${mapName}-tab-${tab}`}
        className={`view-frame editor-scope ${tab === "dm" ? "dm-view" : "characters-view"}`}
      >
        {tab === "dm" && <p className="view-warning">{t("mapState.dmViewWarning")}</p>}
        {tab === "characters" && selected.length === 0 ? (
          <p className="placeholder">{t("mapState.pickCharacters")}</p>
        ) : offline ? (
          <p role="status" className="offline">
            {t("mapState.offline")}
          </p>
        ) : view.error && !(view.error instanceof NeedsToken) ? (
          <p role="alert" className="notice error">
            {t("mapState.viewFailed", { error: view.error.message })}
          </p>
        ) : (
          <div className="view-svg">
            <SvgPreview svg={view.data?.svg ?? null} loading={view.isFetching} />
          </div>
        )}
      </div>
    </section>
  );
}
