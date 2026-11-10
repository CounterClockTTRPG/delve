import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Menu } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { accountKeys, getMe, getTableRequests, isOrganiser } from "../account/api";
import { useMe } from "../account/useMe";
import { ApiError, NeedsToken, getCampaign, hasSheet, listCampaigns, listCharacters, queryKeys } from "../api";
import { useConfirm } from "../components/dialogs";
import { PortraitStyleProvider } from "../components/portraitStyle";
import { usePages } from "../components/Pager";
import { useLanguage, useT, type Translate } from "../i18n";
import BeatTimer from "../play/BeatTimer";
import Composer, { type Refill } from "../play/Composer";
import MissingPack from "../play/MissingPack";
import LookPicker from "../looks/LookPicker";
import AccountUsage from "../play/AccountUsage";
import HostControls from "../play/HostControls";
import MapPanel from "../play/MapPanel";
import PartySidebar from "../play/PartySidebar";
import HotseatTurns, { hotseatTurns, nextTurn, turnsTaken } from "../play/HotseatTurns";
import PendingActs from "../play/PendingActs";
import HistoryPanel, { useHasHistory } from "../play/HistoryPanel";
import SettingPanel from "../play/SettingPanel";
import SeatIndicators from "../play/SeatIndicators";
import TableOptionsPopover from "../play/TableOptionsPopover";
import SheetDrawer from "../play/SheetDrawer";
import Story, { GalleryStrip } from "../play/Story";
import TablePanel from "../play/TablePanel";
import TalkPanel from "../play/TalkPanel";
import { AwayLine, HandsLine, RaisedHands, SessionControls, SessionNotice, actBlocked } from "../play/Session";
import { sessionWhen } from "../play/NextSession";
import Timeline from "../play/Timeline";
import VoiceControls from "../play/VoiceControls";
import VoiceProvider from "../play/voice/VoiceProvider";
import { ProfileCards } from "../profile/ProfileCard";
import ThinkingIndicator from "../play/ThinkingIndicator";
import WorldPanel from "../play/WorldPanel";
import {
  TABLE_ROLES,
  act,
  askDm,
  paintScene,
  cancelBeat,
  getPending,
  getPlayState,
  getSeats,
  endSession,
  comeBack,
  lowerHand,
  passBeat,
  raiseHand,
  resumeSession,
  startSession,
  stepAway,
  takeBreak,
  playKeys,
  sendTyping,
  shareAnswer,
  talk,
  pasteTalkPicture,
  takeDownTalkPicture,
  talkPictureUrl,
  type AbsentChoice,
  type RunningBeat,
  type SeatRole,
} from "../play/api";
import { merge, useStory } from "../play/useStory";
import { usePlayEvents } from "../play/usePlayEvents";
import { takeHeldRequest } from "../play/heldRequest";
import { usePhone } from "../play/usePhone";
import { useNavMenu } from "../components/navMenu";
import { typingStore, useTyping, type Typing, type TypingStore } from "../play/typing";
import { useChanged } from "../play/useChanged";
import Split from "../desktop/Split";
import { useWide } from "../desktop/useMedia";
import { PickCharacters } from "./Join";

/** The server's refusal while a beat runs (`delve.play.table.STILL_ANSWERING`), shown in the reader's language. */
const STILL_ANSWERING = "the DM is still answering";

/** `/play` picks a campaign, the complete ones tagged so; `/play/:campaignId` is its play screen. */
export default function Play() {
  const { campaignId } = useParams();
  return campaignId ? <PlayScreen key={campaignId} campaignId={campaignId} /> : <CampaignPicker />;
}

function CampaignPicker() {
  const t = useT();
  const campaigns = useQuery({ queryKey: queryKeys.campaigns, queryFn: listCampaigns });
  const { shown, pager } = usePages(campaigns.data ?? [], 20, t("pager.labelled", { name: t("area.campaigns") }), {
    param: "page",
  });
  return (
    <section className="page">
      <h1>{t("area.play")}</h1>
      <p className="lede">{t("play.pick")}</p>
      {campaigns.error && !(campaigns.error instanceof NeedsToken) && (
        <p role="alert" className="notice error">
          {t("campaigns.loadFailed", { error: campaigns.error.message })}
        </p>
      )}
      {campaigns.data &&
        (campaigns.data.length === 0 ? (
          <p className="placeholder">
            <Link to="/campaigns">{t("play.noCampaigns")}</Link>
          </p>
        ) : (
          <>
            <ul className="rows">
              {shown.map((c) => (
                <li key={c.id} className="row">
                  <Link to={`/play/${encodeURIComponent(c.id)}`} className="row-title">
                    {c.name}
                  </Link>
                  {/* Done in principle, though it still opens for play (DEL-244). */}
                  {c.status === "complete" && <span className="tag">{t("campaigns.status.complete")}</span>}
                </li>
              ))}
            </ul>
            {pager}
          </>
        ))}
    </section>
  );
}

function errorText(t: Translate, error: unknown): string | null {
  if (!error || error instanceof NeedsToken) return null;
  // A 409 is a beat the DM is still answering, or a session that doesn't allow it yet: the server says which.
  if (error instanceof ApiError && error.status === 409 && (!error.body.error || error.body.error === STILL_ANSWERING))
    return t("play.stillAnswering");
  return (error as Error).message;
}

type PhoneScreen = "map" | "party" | "table" | "world" | "setting" | "history";
const PHONE_SCREENS: { id: PhoneScreen; label: string }[] = [
  { id: "map", label: "play.map" },
  { id: "party", label: "play.party" },
  { id: "table", label: "play.table" },
  { id: "world", label: "play.world" },
  { id: "setting", label: "play.setting" },
  { id: "history", label: "play.history" },
];
/** Beside the story, the sidebar's three tabs: the party, the maps (the panel below) and the table (its talk and seats,
 * then the host's controls). A tab out of sight whose panel changed carries a dot until it is opened. */
type AsideTab = "party" | "map" | "table";
const ASIDE_TABS: { id: AsideTab; label: string }[] = [
  { id: "party", label: "play.party" },
  { id: "map", label: "play.maps" },
  { id: "table", label: "play.table" },
];
/** On desktop, the dungeon map, the world, the campaign's setting and, when it has one, the party's history share the
 * Maps tab, as tabs of their own. */
type SideTab = "map" | "world" | "setting" | "history";
const SIDE_TABS: SideTab[] = ["map", "world", "setting", "history"];

/**
 * A campaign's play screen, as this browser's seat at the table sees it: the owner's owner seat, or a joined seat.
 * The host and co-hosts get the host's controls and the tool rows; an organiser also the table options and the
 * marching order. Beside the story (600 px and over): the Party, Maps and Table tabs, Maps holding the map with the
 * World, the Setting and, for a carried party, its History as tabs beside it, and Table the table panel, then the
 * host's controls; on a phone, World, Setting and History are the bottom bar's fourth, fifth and sixth screens. Party,
 * Maps (Map on a phone) and Table carry a dot while they are out of sight and changed: a PC's hit points, conditions or
 * gear; where the party is, or a map_state event (an area revealed); another seat's talk, or a seat come or gone.
 * A player who plays no character can choose one, with the join page's picker. Table talk has one place (DEL-199): the
 * foot of the side column, under its tabs, with its own box (on a phone, the Table screen); the box under the story
 * speaks to the DM. While the table gathers before a session, and on a break, the side column is wide and the story
 * narrow; the talk's Widen and Narrow switch it by hand. The host and co-hosts start the session, take a break and end
 * it from the header; hands raised at the table show above the side column's tabs and by the Act box. Each player's
 * avatar, in the talk, the seats and the party, opens their profile card (players and tavern Task G3).
 */
function PlayScreen({ campaignId }: { campaignId: string }) {
  const t = useT();
  const client = useQueryClient();
  const phone = usePhone();
  // The app's nav, whose bar a phone's play screen hides: its Menu tab opens it as a sheet (DEL-188).
  const navMenu = useNavMenu();
  const wide = useWide();
  const me = useQuery({ queryKey: playKeys.me(campaignId), queryFn: () => getMe(campaignId) });
  // Without an answer from /api/me this is the owner's own screen, as before seats.
  const mySeat = me.data?.seat ?? null;
  const role: SeatRole = mySeat?.role ?? (me.isError ? "host" : "player");
  const organiser = me.isError || (me.data?.principal.roles.includes("organiser") ?? false);
  // Who this browser is, as the shell reads it: the organiser's side bar has Rulesets, so the header's link is for the
  // others, a seat's link (no side bar) and a player's account (My tables and Preferences only).
  const whoIAm = useMe();
  const rulesetsInSideBar = whoIAm.isError || (whoIAm.data !== undefined && !whoIAm.data.seat && (!whoIAm.data.account || isOrganiser(whoIAm.data.account)));
  const runsTheTable = TABLE_ROLES.has(role);
  const language = mySeat?.language;
  const uiLanguage = useLanguage();
  const story = useStory(campaignId, language, !me.isPending);
  // The talk's own pages (DEL-219): its lines beyond the story's newest page. Lines told live come in the story's.
  const talkPages = useStory(campaignId, language, !me.isPending, "talk");
  const campaign = useQuery({
    queryKey: queryKeys.campaign(campaignId),
    queryFn: () => getCampaign(campaignId),
    enabled: organiser,
  });
  const state = useQuery({ queryKey: playKeys.state(campaignId), queryFn: () => getPlayState(campaignId) });
  const seatsQuery = useQuery({ queryKey: playKeys.seats(campaignId), queryFn: () => getSeats(campaignId) });
  // What the page heard of the beat since the state was last read: the Act answer, or a `beat` event.
  const [heard, setHeard] = useState<{ beat: RunningBeat | null; at: number } | null>(null);
  const [refill, setRefill] = useState<Refill | null>(null);
  // A request for a character asked before the session started waits in the box (DEL-254).
  useEffect(() => {
    const held = takeHeldRequest(campaignId);
    if (held) setRefill((last) => ({ text: held, private: false, n: (last?.n ?? 0) + 1 }));
  }, [campaignId]);
  // Words the server refused (too fast, too long, any error) go back to the box instead of being lost (DEL-153).
  const giveBack = (text: string, mode: "own" | "ask", secret = false) =>
    setRefill((last) => ({ text, private: secret, mode, refused: true, n: (last?.n ?? 0) + 1 }));
  // Talk the server refused goes back into the talk's box.
  const [talkBack, setTalkBack] = useState<{ text: string; n: number } | null>(null);
  // Widen or Narrow, by hand, for the session state it was chosen in; the state's own width otherwise.
  const [widthBy, setWidthBy] = useState<{ state: string; wide: boolean } | null>(null);
  // Who is typing, outside the screen's state: a keystroke at the table re-renders only what shows it (DEL-168).
  const [typing] = useState(typingStore);
  const [sheetId, setSheetId] = useState<string | null>(null);
  // The DM's tool calls in the running beat, as the `beat_tools` events say: the host's and co-hosts' alone.
  const [tools, setTools] = useState<{ beatId: string; count: number } | null>(null);
  const [screen, setScreen] = useState<PhoneScreen | null>(null);
  const [sideTab, setSideTab] = useState<SideTab>("map");
  const [asideTab, setAsideTab] = useState<AsideTab>("party");
  // A sidebar tab mounts when it is first opened, and stays (DEL-168): a tab nobody opened reads nothing.
  const [asideOpened, setAsideOpened] = useState<ReadonlySet<AsideTab>>(() => new Set(["party"]));
  const openAside = (tab: AsideTab) => {
    setAsideTab(tab);
    setAsideOpened((opened) => (opened.has(tab) ? opened : new Set([...opened, tab])));
  };
  // map_state events heard: a map's areas revealed or changed, which the state's positions alone don't show.
  const [mapEvents, setMapEvents] = useState(0);
  // The History tab and screen are there only when the campaign has a history.
  const hasHistory = useHasHistory(campaignId);
  const sideTabs = SIDE_TABS.filter((tab) => tab !== "history" || hasHistory);
  const phoneScreens = PHONE_SCREENS.filter((tab) => tab.id !== "history" || hasHistory);
  const [left, setLeft] = useState(false);
  const [picking, setPicking] = useState(false);
  // The sheets: the one opened in the drawer, and the portraits on the party sidebar.
  const characters = useQuery({
    queryKey: queryKeys.characters(campaignId),
    queryFn: () => listCharacters(campaignId),
  });

  const beat = heard && heard.at >= state.dataUpdatedAt ? heard.beat : (state.data?.beat ?? null);
  // An open beat waits for the table; a running one is the DM answering.
  const beatOpen = beat?.status === "open";
  const thinking = beat?.status === "running";
  const toolsSeen = beat ? story.entries.filter((e) => e.kind === "tool" && e.beat_id === beat.id).length : 0;
  const submitted = beatOpen ? (beat.submitted ?? []) : [];
  // The open beat's acts so far, as the server lets this seat see them (an observer: none).
  const pendingQuery = useQuery({
    queryKey: playKeys.pending(campaignId),
    queryFn: () => getPending(campaignId),
    enabled: beatOpen,
  });
  const pending = beatOpen ? (pendingQuery.data?.pending ?? []) : [];

  const data = state.data;
  const tableSession = data?.table;
  const sessionState = tableSession?.state ?? "playing";
  // Alone at the table (no other seat that hasn't left, observers too), talk has nobody to talk to: it is left out,
  // and the side column is the panels' (DEL-232).
  const alone = seatsQuery.isSuccess && seatsQuery.data.every((s) => s.id === mySeat?.id);
  const talkWide =
    !phone && !alone && (widthBy?.state === sessionState ? widthBy.wide : sessionState === "gathering" || sessionState === "break");
  const hands = tableSession?.hands ?? [];
  const party = data?.party ?? [];
  const portraits = Object.fromEntries((characters.data ?? []).filter(hasSheet).map((c) => [c.id, c.sheet.portrait]));
  const sheets = Object.fromEntries((characters.data ?? []).filter(hasSheet).map((c) => [c.id, c]));
  // The faces on the fight's tokens and the timeline (DEL-10), kept while nothing in them changes, so the map's SVG
  // isn't decorated again on every render.
  // Kept while the names are the same, so the story's entries needn't render again (DEL-168).
  const nameKey = JSON.stringify(party.map((m) => [m.id, m.name]));
  const names = useMemo<Record<string, string>>(() => Object.fromEntries(JSON.parse(nameKey)), [nameKey]);
  const faceKey = JSON.stringify(party.map((m) => [m.id, portraits[m.id] ?? null, m.hp, m.hp_max]));
  const faces = useMemo(
    () => Object.fromEntries(party.map((m) => [m.id, { portrait: portraits[m.id] ?? null, hp: m.hp, hpMax: m.hp_max }])),
    // By what they show: a new party of the same faces decorates nothing again.
    [faceKey],
  );
  const seats = seatsQuery.data ?? [];
  const mySeatId = mySeat?.id ?? null;
  // The host acts for the PCs nobody plays, as well as their own.
  const played = new Set(seats.flatMap((s) => s.characters));
  const own = new Set(seats.find((s) => s.id === mySeatId)?.characters ?? []);
  const myCharacters = party.filter((m) => own.has(m.id) || (runsTheTable && !played.has(m.id)));
  const others = seats.filter((s) => s.id !== mySeatId && s.present);
  // A player whose seat plays nothing (a reload before picking, say) has no way to act yet.
  const noCharacter = mySeat !== null && role === "player" && seatsQuery.isSuccess && own.size === 0;
  const actingSeats = seats.filter((s) => s.role !== "observer");
  // Several players at this screen (DEL-365): the box is the current turn's, and goes round after each act or pass.
  const turns = hotseatTurns(data?.hotseat, mySeatId, myCharacters.map((m) => m.id), mySeat?.name ?? "");
  const taken = turnsTaken(pending, mySeatId);
  const [turnId, setTurnId] = useState<string | null | undefined>(undefined);
  const turn = turns ? (turns.find((x) => x.id === turnId) ?? turns.find((x) => !taken.has(x.id)) ?? turns[0]) : null;
  const myAct = pending.find(
    (p) => p.seat_id === mySeatId && p.kind === "act" && (turn === null || (p.hotseat ?? null) === turn.id),
  );
  // A beat the DM answers, or none, starts the next round of turns at the first player.
  const beatStatus = beat?.status;
  useEffect(() => {
    if (beatStatus !== "open") setTurnId(undefined);
  }, [beatStatus]);
  const turnTaken = (id: string | null) => {
    if (turns) setTurnId(nextTurn(turns, new Set([...taken, id]), id));
  };

  const refetchState = () => client.invalidateQueries({ queryKey: playKeys.state(campaignId) });
  const submittedNow = (opened: RunningBeat) => {
    setHeard({ beat: opened, at: Date.now() });
    client.invalidateQueries({ queryKey: playKeys.pending(campaignId) });
    void story.refresh();
  };

  const acting = useMutation({
    mutationFn: ({ text, characters, secret, player }: { text: string; characters?: string[]; secret?: boolean; player?: string | null }) =>
      act(campaignId, text, characters, secret, player ?? undefined),
    onSuccess: ({ beat: opened }, { player }) => {
      if (player !== undefined) turnTaken(player);
      submittedNow(opened);
    },
    onError: (_error, { text, secret }) => {
      giveBack(text, "own", secret);
      refetchState();
    },
  });
  const passing = useMutation({
    mutationFn: ({ characters, player }: { characters?: string[]; player?: string | null }) =>
      passBeat(campaignId, characters, player ?? undefined),
    onSuccess: ({ beat: opened }, { player }) => {
      if (player !== undefined) turnTaken(player);
      submittedNow(opened);
    },
    onError: () => refetchState(),
  });
  const talking = useMutation({
    mutationFn: (text: string) => talk(campaignId, text),
    onSuccess: ({ entry }) => story.add(entry),
    onError: (_error, text) => setTalkBack((last) => ({ text, n: (last?.n ?? 0) + 1 })),
  });
  // A picture pasted into table talk (DEL-294), and one taken down: the line comes back as the table hears it.
  const picturing = useMutation({
    mutationFn: (file: File) => pasteTalkPicture(campaignId, file),
    onSuccess: ({ entry }) => story.add(entry),
  });
  const takingDown = useMutation({
    mutationFn: (entryId: string) => takeDownTalkPicture(campaignId, entryId),
    onSuccess: ({ entry }) => story.add(entry),
  });
  // The session's steps and the raised hands: the state is read again, and the beat a start or an end opened is heard.
  const session = useMutation({
    mutationFn: (step: { kind: "start"; absent: Record<string, AbsentChoice> } | { kind: "break" | "resume" | "end" }) =>
      step.kind === "start"
        ? startSession(campaignId, step.absent)
        : step.kind === "break"
          ? takeBreak(campaignId)
          : step.kind === "resume"
            ? resumeSession(campaignId)
            : endSession(campaignId),
    onSuccess: (answer) => {
      const opened = (answer as { beat?: RunningBeat }).beat;
      if (opened) submittedNow(opened);
      refetchState();
    },
  });
  const hand = useMutation({
    mutationFn: (step: { raise: string | null } | { lower: string }) =>
      "lower" in step ? lowerHand(campaignId, step.lower) : raiseHand(campaignId, step.raise),
    onSettled: () => refetchState(),
  });
  // Stepping away mid-session, and back (DEL-224).
  const awayStep = useMutation({
    mutationFn: (step: { away: AbsentChoice | null } | { back: string }) =>
      "back" in step ? comeBack(campaignId, step.back) : stepAway(campaignId, step.away),
    onSettled: () => refetchState(),
  });
  const sharing = useMutation({
    mutationFn: (answerId: string) => shareAnswer(campaignId, answerId),
    onSuccess: ({ entry }) => story.add(entry),
  });
  const share = sharing.mutate;
  const onShare = useCallback((answerId: string) => share(answerId), [share]);
  const cancel = useMutation({ mutationFn: () => cancelBeat(campaignId), onSettled: () => refetchState() });
  // Paint this scene: the picture comes into the story as a `scene` entry once it is painted.
  const painting = useMutation({ mutationFn: () => paintScene(campaignId) });
  // The question and its answer come back as story events, for this seat alone (and translated for it): the server
  // publishes both, so the story isn't read again for them (DEL-168).
  const asking = useMutation({
    mutationFn: (question: string) => askDm(campaignId, question),
    onError: (_error, question) => giveBack(question, "ask"),
  });
  // The Composer shows the error of the last thing tried, so an old failure goes once something newer is tried
  // (DEL-174); and "being painted" goes once the scene asked for is in the story.
  const lastTried = [acting, passing, asking, sharing, cancel, painting, session, hand, awayStep].reduce((last, m) =>
    m.submittedAt > last.submittedAt ? m : last,
  );
  const paintedLanded = story.entries.some((e) => e.kind === "scene" && e.payload.image_id === painting.data?.image_id);
  // Paint this scene asks first, and says when it costs the host money (DEL-258: a click painted at once, two clicks
  // two paintings). One at a time: it waits while the one asked for is painting.
  const confirmPaint = useConfirm();
  const paintingNow = painting.isPending || (painting.isSuccess && !paintedLanded);
  async function paintAfterAsking() {
    if (paintingNow) return;
    const sure = await confirmPaint({
      title: t("play.paintConfirm"),
      body: t(data?.scene_paid ? "play.paintConfirm.paid" : "play.paintConfirm.free"),
      confirm: t("play.paintConfirm.go"),
    });
    if (sure) painting.mutate();
  }

  // Live updates, for this campaign only.
  usePlayEvents({ campaignId, language, story, talkPages, typing, setHeard, setMapEvents, setTools });

  // The table's requests to join, for the host's and co-hosts' dot on Table; Host controls show them.
  const joinRequests = useQuery({
    queryKey: accountKeys.tableRequests(campaignId),
    queryFn: () => getTableRequests(campaignId),
    enabled: runsTheTable,
  });

  // What each dotted tab shows, summed up for `useChanged` (null while it loads).
  const changed = {
    party: useChanged(
      data && characters.data
        ? JSON.stringify([
            party.map((m) => [m.id, m.hp, m.hp_max, m.conditions]),
            characters.data.filter(hasSheet).map((c) => [c.id, c.state?.inventory ?? null]),
          ])
        : null,
      phone ? screen === "party" : asideTab === "party",
    ),
    map: useChanged(data ? JSON.stringify([data.positions, mapEvents]) : null, phone ? screen === "map" : asideTab === "map"),
    table: useChanged(
      seatsQuery.data
        ? JSON.stringify([
            phone
              ? story.entries
                  .filter((e) => e.kind === "talk" && e.live && (e.payload as { seat_id?: string }).seat_id !== mySeatId)
                  .map((e) => e.id)
              : [],
            seats.map((s) => [s.id, s.present]),
            // A new request to join puts a dot on Table for the host and co-hosts (DEL-204).
            (joinRequests.data ?? []).filter((r) => r.status === "pending").map((r) => r.id),
          ])
        : null,
      phone ? screen === "table" : asideTab === "table",
    ),
  };
  const dot = (tab: AsideTab) =>
    changed[tab] ? (
      <>
        <span className="tab-dot" data-testid={`dot-${tab}`} aria-hidden="true" />
        <span className="visually-hidden">{t("play.changed")}</span>
      </>
    ) : null;

  if (left) {
    return (
      <section className="page">
        <p className="notice" role="status">
          {t("play.left")}
        </p>
      </section>
    );
  }

  // An unknown campaign (a stale link, a typo): a plain page, without the story or the header.
  if (state.error instanceof ApiError && state.error.status === 404) {
    return (
      <section className="page">
        <h1>{t("area.play")}</h1>
        <p role="alert" className="notice error">
          {t("play.notFound")}
        </p>
        <p>
          <Link to="/play">{t("play.pickAnother")}</Link>
        </p>
      </section>
    );
  }

  const sheet = characters.data?.filter(hasSheet).find((c) => c.id === sheetId);
  // Who may repaint a portrait (DEL-135, the owner's choice): the host, a co-host or an organiser any; a player their
  // own PC. The server checks it again.
  const mayRepaint = (characterId: string) => organiser || runsTheTable || (role === "player" && own.has(characterId));
  const loadError = errorText(t, state.error ?? story.error);

  const mapPanel = (
    <MapPanel
      campaignId={campaignId}
      party={party}
      faces={faces}
      positions={data?.positions ?? []}
      viewable={runsTheTable ? undefined : myCharacters.map((m) => m.id)}
      fitWhole={phone}
    />
  );
  const partyPanel = (
    <PartySidebar
      campaignId={campaignId}
      party={party}
      onOpenSheet={setSheetId}
      canReorder={organiser}
      portraits={portraits}
      onPregens={runsTheTable ? (text) => acting.mutate({ text }) : undefined}
      pregensBusy={acting.isPending || thinking}
      pregensBlocked={actBlocked(t, tableSession)}
      levelFit={runsTheTable ? data?.level_fit : null}
      coin={data?.coin}
      seats={seats}
      departed={data?.departed}
      sheets={sheets}
    />
  );
  const pictureError = errorText(t, picturing.error ?? takingDown.error);
  // The talk's own pages and the lines the story has, live ones among them, as one list (the story's copy wins).
  const talkEntries = merge(
    story.entries.filter((e) => e.kind === "talk"),
    talkPages.entries.filter((e) => !story.entries.some((s) => s.id === e.id)),
  );
  const tablePanel = (
    <TablePanel
      campaignId={campaignId}
      campaignName={campaign.data?.name ?? mySeat?.campaign_name ?? ""}
      seats={seats}
      mySeat={{ id: mySeatId ?? "", role }}
      onLeft={() => setLeft(true)}
    />
  );
  const myHand = hands.find((h) => h.seat_id === mySeatId);
  const awaySeats = (tableSession?.away ?? []).map((a) => a.seat_id);
  const iAmAway = mySeatId !== null && awaySeats.includes(mySeatId);
  // Stepping away is for a seat that plays, while a session with others is under way.
  const mayStepAway = mySeatId !== null && role !== "observer" && sessionState !== "gathering" && !tableSession?.solo;
  const talkPanel = (
    <WithTyping store={typing}>
      {(typingNow) => (
    <TalkPanel
      entries={talkEntries}
      hasMore={talkPages.hasMore}
      loadingEarlier={talkPages.loadingEarlier}
      onLoadEarlier={() => void talkPages.loadEarlier()}
      mySeatId={mySeatId}
      seats={seats}
      typing={typingNow}
      onTalk={(text) => talking.mutate(text)}
      talking={talking.isPending || picturing.isPending}
      error={
        errorText(t, talking.error) ??
        (pictureError && t("play.talkPictureFailed", { error: pictureError })) ??
        errorText(t, talkPages.error)
      }
      pictureUrl={(entryId) => talkPictureUrl(campaignId, entryId)}
      onPicture={data?.talk_pictures && role !== "observer" ? (file) => picturing.mutate(file) : undefined}
      onTakeDown={(entryId) => takingDown.mutate(entryId)}
      mayTakeDown={(entry) => runsTheTable || (mySeatId !== null && entry.payload.seat_id === mySeatId)}
      onTyping={others.length > 0 ? (typingNow) => void sendTyping(campaignId, typingNow).catch(() => {}) : undefined}
      giveBack={talkBack}
      hand={
        mySeatId
          ? {
              mine: myHand,
              onRaise: (point) => hand.mutate({ raise: point }),
              onLower: () => hand.mutate({ lower: mySeatId }),
              busy: hand.isPending,
            }
          : undefined
      }
      away={
        mayStepAway
          ? { away: iAmAway, onStepAway: (part) => awayStep.mutate({ away: part }), busy: awayStep.isPending }
          : undefined
      }
      wide={talkWide}
      onWiden={phone ? undefined : () => setWidthBy({ state: sessionState, wide: !talkWide })}
      foldable={!phone}
    />
      )}
    </WithTyping>
  );
  const raisedHands = (
    <RaisedHands
      hands={hands}
      seats={seats}
      mySeatId={mySeatId}
      runsTheTable={runsTheTable}
      playing={sessionState === "playing"}
      onLower={(seatId) => hand.mutate({ lower: seatId })}
      onBreak={() => session.mutate({ kind: "break" })}
    />
  );
  // Once the seats are in, which always hold this one.
  const hostPanel =
    runsTheTable && seats.length > 0 ? (
      <HostControls
        campaignId={campaignId}
        seats={seats}
        party={party}
        mySeat={{ id: mySeatId ?? "", role }}
        beatOpen={beatOpen}
        table={tableSession}
      />
    ) : null;
  const picked = () => {
    setPicking(false);
    client.invalidateQueries({ queryKey: playKeys.seats(campaignId) });
    client.invalidateQueries({ queryKey: queryKeys.characters(campaignId) });
    refetchState();
  };

  const storyColumn = (
  <div className="play-main">
    <Timeline campaignId={campaignId} phone={phone} faces={faces} canPaint={organiser} />
    <Story
      entries={story.entries}
      hasMore={story.hasMore}
      loadingEarlier={story.loadingEarlier}
      onLoadEarlier={() => void story.loadEarlier()}
      mySeatId={mySeatId}
      names={names}
      role={role}
      waiting={tableSession?.state === "gathering" && !tableSession.solo}
      asking={asking.isPending ? asking.variables : null}
      onShare={alone ? undefined : onShare}
      campaignId={campaignId}
      paintingScenes={data?.painting_scenes}
      running={thinking}
    />
    {thinking && beat && (
      <ThinkingIndicator
        key={beat.id}
        campaignId={campaignId}
        elapsedS={beat.elapsed_s}
        toolCount={runsTheTable ? Math.max(tools?.beatId === beat.id ? tools.count : 0, toolsSeen) : undefined}
      />
    )}
    {tableSession && <SessionNotice table={tableSession} seats={seats} runsTheTable={runsTheTable} />}
    {((actingSeats.length > 1 && sessionState === "playing") || (beatOpen && beat.deadline)) && (
      <div className="beat-bar">
        {actingSeats.length > 1 && sessionState === "playing" && (
          <WithTyping store={typing}>
            {(typingNow) => (
              <SeatIndicators seats={seats} typing={typingNow} submitted={submitted} mySeatId={mySeatId} away={awaySeats} />
            )}
          </WithTyping>
        )}
        <BeatTimer deadline={beatOpen ? beat.deadline : null} />
      </div>
    )}
    {noCharacter && (
      <div className="choose-character notice" role="status">
        <span>{t("play.noCharacter")}</span>
        <button type="button" className="primary" onClick={() => setPicking(true)}>
          {t("play.chooseCharacter")}
        </button>
      </div>
    )}
    {beatOpen && (
      <PendingActs
        pending={pending}
        mySeatId={mySeatId}
        names={names}
        onChange={({ hotseat, ...was }) => {
          if (turns) setTurnId(hotseat ?? null);
          setRefill((last) => ({ ...was, n: (last?.n ?? 0) + 1 }));
        }}
      />
    )}
    {turns && turn && !data?.missing_pack && (
      <HotseatTurns turns={turns} taken={taken} current={turn.id} onPick={setTurnId} />
    )}
    {data?.missing_pack ? (
      <MissingPack kind={data.missing_pack.kind} id={data.missing_pack.id} />
    ) : (
      <Composer
        running={thinking}
        asking={asking.isPending}
        error={errorText(t, lastTried.error)}
        canAct={role !== "observer"}
        canCancel={runsTheTable}
        beatOpen={beatOpen}
        replacing={myAct !== undefined}
        refill={refill}
        characters={(turn ? party.filter((m) => turn.characters.includes(m.id)) : myCharacters).map((m) => ({ id: m.id, name: m.name }))}
        onAct={(text, characters, secret) =>
          acting.mutate({ text, characters, secret, ...(turn ? { player: turn.id } : {}) })
        }
        onPass={(characters) => passing.mutate({ characters, ...(turn ? { player: turn.id } : {}) })}
        canPrivate={turn === null}
        actingAs={turn?.id ? turn.name : null}
        onAsk={(question) => asking.mutate(question)}
        onCancel={() => cancel.mutate()}
        onTyping={others.length > 0 ? (typingNow) => void sendTyping(campaignId, typingNow).catch(() => {}) : undefined}
        onPaint={data?.scene_painting && role !== "observer" ? () => void paintAfterAsking() : undefined}
        painting={painting.isPending}
        painted={painting.isSuccess && !paintedLanded}
        blocked={actBlocked(t, tableSession)}
        notice={
          <>
            {iAmAway && mySeatId && (
              <AwayLine onBack={() => awayStep.mutate({ back: mySeatId })} busy={awayStep.isPending} />
            )}
            <HandsLine hands={hands} seats={seats} mySeatId={mySeatId} />
          </>
        }
      />
    )}
  </div>
  );

  const asideColumn = (
  <aside className={talkWide ? "play-aside talk-wide" : "play-aside"} data-testid="play-aside">
    {raisedHands}
    <div className="aside-tabs" role="tablist" aria-label={t("play.sidebar")}>
      {ASIDE_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`aside-tab-${tab.id}`}
          aria-selected={asideTab === tab.id}
          aria-controls={`aside-panel-${tab.id}`}
          onClick={() => openAside(tab.id)}
        >
          {t(tab.label)}
          {dot(tab.id)}
        </button>
      ))}
    </div>
    <div className="play-party" data-panel="party" role="tabpanel" id="aside-panel-party" aria-labelledby="aside-tab-party" hidden={asideTab !== "party"}>
      {asideOpened.has("party") && partyPanel}
    </div>
    <div className="play-side" data-panel="map" role="tabpanel" id="aside-panel-map" aria-labelledby="aside-tab-map" hidden={asideTab !== "map"}>
      {asideOpened.has("map") && (
      <>
      <div className="side-tabs" role="tablist" aria-label={t("play.panels")}>
        {sideTabs.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`side-tab-${tab}`}
            aria-selected={sideTab === tab}
            aria-controls="side-tab-panel"
            onClick={() => setSideTab(tab)}
          >
            {t(`play.${tab}`)}
          </button>
        ))}
      </div>
      <div id="side-tab-panel" role="tabpanel" aria-labelledby={`side-tab-${sideTab}`}>
        {sideTab === "map" ? (
          mapPanel
        ) : sideTab === "world" ? (
          <WorldPanel campaignId={campaignId} />
        ) : sideTab === "history" && hasHistory ? (
          <HistoryPanel campaignId={campaignId} />
        ) : (
          <SettingPanel campaignId={campaignId} />
        )}
      </div>
      </>
      )}
    </div>
    <div className="play-table" data-panel="table" role="tabpanel" id="aside-panel-table" aria-labelledby="aside-tab-table" hidden={asideTab !== "table"}>
      {asideOpened.has("table") && (
        <>
          <div data-panel="table-panel">{tablePanel}</div>
          {hostPanel && (
            <div className="play-host" data-panel="host">
              {hostPanel}
            </div>
          )}
        </>
      )}
    </div>
    {!alone && (
      <div className="play-talk" data-panel="talk">
        {talkPanel}
      </div>
    )}
  </aside>
  );

  return (
    <PortraitStyleProvider campaignId={campaignId}>
      <ProfileCards>
        <VoiceProvider campaignId={campaignId} allowed={data?.voice !== "off"} role={role}>
        <div className={phone ? "play phone" : "play"}>
          <header className="play-head" data-tour="play-head">
            <h1>{campaign.data?.name ?? mySeat?.campaign_name ?? t("area.play")}</h1>
            {data && (
              // "1 Planting 576 CY" is the game world's date: the line says what its parts are on hover (DEL-266).
              <p className="row-meta" title={t("play.headMetaExplain")}>
                {[
                  data.session_number !== null
                    ? t(data.session_over ? "play.sessionOver" : "play.session", { number: String(data.session_number) })
                    : null,
                  // While the table waits for its session, when it is (DEL-204 part C), in the viewer's own time.
                  sessionState !== "playing" && data.next_sessions?.[0]
                    ? t("schedule.next", { when: sessionWhen(data.next_sessions[0], uiLanguage) })
                    : null,
                  data.time_of_day,
                  data.date,
                  data.weather?.label,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            )}
            <GalleryStrip entries={story.entries} />
            {/* The rules to look up, beside the table rather than instead of it (rulesets plan, Decision 9), with the table's
                house rules: an account's area knows its table only by the `?campaign=`. An icon, for those whose side bar
                has no Rulesets. */}
            {!rulesetsInSideBar && whoIAm.data !== undefined && (
              <a
                className="rulesets-link icon-link"
                href={`/rulesets${data?.ruleset ? `/${encodeURIComponent(data.ruleset)}` : ""}?campaign=${encodeURIComponent(campaignId)}`}
                target="_blank"
                rel="noopener"
                aria-label={t("rulesets.opensTab")}
                title={t("rulesets.opensTab")}
                data-testid="rulesets-link"
              >
                {/* A word beside the icon where the header has room (DEL-259). */}
                <BookOpen size={18} aria-hidden="true" /> <span className="head-tool-label">{t("rulesets.short")}</span>
              </a>
            )}
            {role === "host" && <AccountUsage campaignId={campaignId} />}
            <LookPicker compact />
            {runsTheTable && tableSession && (
              <SessionControls
                table={tableSession}
                seats={seats}
                party={party}
                busy={session.isPending || thinking}
                beatOpen={beatOpen}
                onStart={(absent) => session.mutate({ kind: "start", absent })}
                onBreak={() => session.mutate({ kind: "break" })}
                onResume={() => session.mutate({ kind: "resume" })}
                onEnd={() => session.mutate({ kind: "end" })}
              />
            )}
            {organiser && runsTheTable && <TableOptionsPopover campaignId={campaignId} />}
            {!phone && <VoiceControls />}
          </header>
          {loadError && (
            <p role="alert" className="notice error play-error">
              {loadError}
            </p>
          )}

          {wide ? (
            // The wide talk is a split of its own, so each browser remembers both widths.
            <Split
              key={talkWide ? "talk" : "story"}
              id={talkWide ? "play-talk" : "play"}
              className="play-body"
              start={{ size: talkWide ? 45 : 72, min: 320, children: storyColumn }}
              end={{ size: talkWide ? 55 : 28, min: 256, children: asideColumn }}
            />
          ) : (
            <>
              {storyColumn}
              {!phone && asideColumn}
            </>
          )}

          {phone && screen && (
            <section className="phone-screen" data-testid="phone-screen" aria-label={t(`play.${screen}`)}>
              <button type="button" className="phone-back" onClick={() => setScreen(null)}>
                {t("play.backToStory")}
              </button>
              {screen === "map" ? (
                mapPanel
              ) : screen === "party" ? (
                partyPanel
              ) : screen === "world" ? (
                <WorldPanel campaignId={campaignId} />
              ) : screen === "setting" ? (
                <SettingPanel campaignId={campaignId} />
              ) : screen === "history" ? (
                <HistoryPanel campaignId={campaignId} />
              ) : (
                // Spaced as the side column is: the talk ran into "At the table" (DEL-263).
                <div className="phone-table">
                  <VoiceControls />
                  {raisedHands}
                  {!alone && talkPanel}
                  {tablePanel}
                  {hostPanel}
                </div>
              )}
            </section>
          )}
          {phone && (
            <nav className="play-tabs" data-testid="phone-tabs" data-tour="play-tabs" aria-label={t("play.panels")}>
              {phoneScreens.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  data-testid={`tab-${tab.id}`}
                  aria-pressed={screen === tab.id}
                  onClick={() => setScreen(screen === tab.id ? null : tab.id)}
                >
                  {t(tab.label)}
                  {(tab.id === "party" || tab.id === "map" || tab.id === "table") && dot(tab.id)}
                </button>
              ))}
              {navMenu && (
                <button
                  type="button"
                  className="play-menu"
                  data-testid="tab-menu"
                  aria-expanded={navMenu.open}
                  aria-controls="nav"
                  aria-label={t("nav.menu")}
                  title={t("nav.menu")}
                  onClick={() => navMenu.setOpen(!navMenu.open)}
                >
                  <Menu size={20} aria-hidden="true" />
                </button>
              )}
            </nav>
          )}

          {sheetId !== null && (
            <SheetDrawer character={sheet} onClose={() => setSheetId(null)} mayRepaint={mayRepaint(sheetId)} />
          )}
          {picking && (
            <div className="play-pick" role="dialog" aria-modal="true" aria-label={t("join.pick")}>
              <PickCharacters campaignId={campaignId} onDone={picked} onCancel={() => setPicking(false)} />
            </div>
          )}
        </div>
        </VoiceProvider>
      </ProfileCards>
    </PortraitStyleProvider>
  );
}

/** What shows who is typing, rendered again on its own as that changes (DEL-168). */
function WithTyping({ store, children }: { store: TypingStore; children: (typing: Typing) => ReactNode }) {
  return <>{children(useTyping(store))}</>;
}
