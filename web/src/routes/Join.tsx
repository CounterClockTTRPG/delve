import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { joinAsAccount, joinWithNewAccount, logIn, logOut, type JoinAnswer, type JoinYou } from "../account/api";
import { ForgotPassword } from "../account/Login";
import "../account/account.css";
import { ApiError, hasSheet, listCharacters, type Character } from "../api";
import { isDead } from "../campaign/CarryForm";
import { I18nProvider, LANGUAGES, isLanguage, useT } from "../i18n";
import { classTerms, term } from "../i18n/terms";
import { act, claimCharacter, getJoinLink, getPlayState, getSeats, playKeys, type JoinLink, type ObserverRule } from "../play/api";
import { holdRequest } from "../play/heldRequest";
import TableAbout from "../play/TableAbout";
import Avatar from "../profile/Avatar";
import { profileKeys, type ProfileSummary } from "../profile/api";

const OTHER = "other";
const CODE = /^[a-z]{2,3}$/;

/** The interface language a newcomer gets first: their browser's, when Delve speaks it. */
function browserLanguage(): string {
  const code = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  return isLanguage(code) ? code : "en";
}

/** `/join/:token` on its own, outside the app: it needs no token, and its 401s mean nothing yet. */
export function JoinRoot() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <Join />
    </QueryClientProvider>
  );
}

/**
 * Joining a table with the host's link (spec §7.2; players and tavern Task E2). Every invite asks for an account: make
 * one (a username, a password, a display name, a language: English, Nederlands or another code) or log in to one,
 * then Play or Watch. A player then picks among the free characters, or asks the DM to make one, which becomes their
 * first act. An account seated here already goes straight to its table. The screen speaks the language picked, when
 * Delve has it.
 */
export default function Join() {
  const [language, setLanguage] = useState(browserLanguage);
  return (
    <I18nProvider language={language === OTHER ? "en" : language}>
      <JoinForm language={language} onLanguage={setLanguage} />
    </I18nProvider>
  );
}

type Role = "player" | "observer";

function JoinForm({ language, onLanguage }: { language: string; onLanguage: (language: string) => void }) {
  const t = useT();
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const link = useQuery({
    queryKey: ["join", token],
    queryFn: () => getJoinLink(token) as Promise<JoinLink & { you: JoinYou | null }>,
  });
  const [tab, setTab] = useState<"make" | "login">("make");
  const [role, setRole] = useState<Role>("player");
  const [campaignId, setCampaignId] = useState<string | null>(null);
  // Asked to watch where a host lets watchers in (DEL-215): the request is the host's to answer.
  const [askedToWatch, setAskedToWatch] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const you = link.data?.you ?? null;
  const seated = Boolean(you?.seat_id);

  /** Seated: a player picks characters, an observer goes to the table; asked to watch: wait for the host. */
  function joined(answer: JoinAnswer, as: Role) {
    if (answer.join_request) setAskedToWatch(true);
    else if (as === "observer") navigate(`/play/${encodeURIComponent(answer.campaign_id)}`, { replace: true });
    else setCampaignId(answer.campaign_id);
  }

  async function attempt(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (failed) {
      setError(t("join.failed", { error: (failed as Error).message }));
    } finally {
      setBusy(false);
    }
  }

  // An account with a seat here already goes straight to its table: joining again answers that seat.
  const going = useRef(false);
  useEffect(() => {
    if (!seated || going.current) return;
    going.current = true;
    joinAsAccount(token, { role: "player" })
      .then((answer) => navigate(`/play/${encodeURIComponent(answer.campaign_id)}`, { replace: true }))
      .catch((failed: Error) => setError(t("join.failed", { error: failed.message })));
  }, [navigate, seated, t, token]);

  // A full table takes no more players; watching stays open (DEL-204), unless the table takes no observers (DEL-215).
  const full = link.data?.campaign.full === true;
  const watching = link.data?.campaign.observers ?? "anyone";
  useEffect(() => {
    if (full && watching !== "nobody") setRole("observer");
  }, [full, watching]);

  if (campaignId) return <PickCharacters campaignId={campaignId} />;

  const roles = <RolePicker role={role} onRole={setRole} full={full} watching={watching} />;
  const alert = error && (
    <p className="notice error" role="alert">
      {error}
    </p>
  );

  return (
    <main className="gate join">
      <div className="gate-card">
        <h1>{t("join.title")}</h1>
        {link.isPending && <p className="placeholder">{t("join.loading")}</p>}
        {link.error && (
          <p className="notice error" role="alert">
            {link.error.message}
          </p>
        )}
        {link.data && (
          <>
            <p className="join-campaign">{link.data.campaign.name}</p>
            {link.data.campaign.host && !you && (
              <p className="join-invited" data-testid="join-invited">
                {t("join.invitedBy", { host: link.data.campaign.host })}
              </p>
            )}
            {link.data.campaign.module_title && (
              <p className="lede">{t("join.module", { module: link.data.campaign.module_title })}</p>
            )}
            {/* For whoever has only the link: what this is, and that the host starts the game (DEL-264). */}
            {!you && (
              <p className="hint join-what" data-testid="join-what">
                {t("join.whatIsDelve")}
              </p>
            )}
            <TableAbout about={link.data.campaign} heading={false} />
            {full && !seated && (
              <p className="notice" role="status" data-testid="join-full">
                {t(watching === "nobody" ? "join.fullNoWatching" : "join.full")}
              </p>
            )}
            {askedToWatch ? (
              <p className="notice" role="status" data-testid="join-asked-to-watch">
                {t("join.askedToWatch")} <Link to="/tables">{t("tables.title")}</Link>
              </p>
            ) : seated ? (
              <>
                <p className="placeholder">{t("join.loading")}</p>
                {alert}
              </>
            ) : you ? (
              <>
                <YouAre
                  profile={you.profile}
                  onLogOut={() =>
                    attempt(async () => {
                      await logOut();
                      client.removeQueries({ queryKey: profileKeys.own });
                      await link.refetch();
                    })
                  }
                />
                <SeatForm
                  displayName={you.display_name}
                  roles={roles}
                  alert={alert}
                  busy={busy}
                  onJoin={(name) =>
                    attempt(async () => {
                      const answer = await joinAsAccount(token, { role, ...(name ? { name } : {}) });
                      joined(answer, role);
                    })
                  }
                />
              </>
            ) : (
              <>
                <div role="tablist" className="view-tabs join-tabs" aria-label={t("join.title")}>
                  {(["make", "login"] as const).map((name) => (
                    <button
                      key={name}
                      type="button"
                      role="tab"
                      id={`join-tab-${name}`}
                      aria-selected={tab === name}
                      aria-controls={`join-panel-${name}`}
                      className="view-tab"
                      onClick={() => {
                        setTab(name);
                        setError(null);
                      }}
                    >
                      {t(name === "make" ? "join.makeAccount" : "join.logIn")}
                    </button>
                  ))}
                </div>
                {tab === "make" ? (
                  <MakeAccount
                    language={language}
                    onLanguage={onLanguage}
                    roles={roles}
                    alert={alert}
                    busy={busy}
                    onMake={(account) =>
                      attempt(async () => {
                        const answer = await joinWithNewAccount(token, { ...account, role });
                        joined(answer, role);
                      })
                    }
                  />
                ) : (
                  <LogIn
                    alert={alert}
                    busy={busy}
                    onLogIn={(username, password) =>
                      attempt(async () => {
                        // On a join page, a sign-up that waits for approval is let in: the host vouched (DEL-156).
                        await logIn(username, password, token);
                        // The link again, which now names the account (and its seat here, if it has one).
                        await client.invalidateQueries({ queryKey: ["join", token] });
                      })
                    }
                  />
                )}
              </>
            )}
          </>
        )}
      </div>
    </main>
  );
}

function RolePicker({
  role,
  onRole,
  full = false,
  watching = "anyone",
}: {
  role: Role;
  onRole: (role: Role) => void;
  full?: boolean;
  /** Who may watch (DEL-215): no Watch at a table that takes none; at one whose host lets watchers in, Watch asks. */
  watching?: ObserverRule;
}) {
  const t = useT();
  return (
    <fieldset className="join-role">
      <legend>{t("join.role")}</legend>
      <label>
        <input
          type="radio"
          name="join-role"
          data-testid="join-role-player"
          checked={role === "player"}
          disabled={full}
          onChange={() => onRole("player")}
        />
        {t("join.play")}
      </label>
      <label>
        <input
          type="radio"
          name="join-role"
          data-testid="join-role-observer"
          checked={role === "observer"}
          disabled={watching === "nobody"}
          onChange={() => onRole("observer")}
        />
        {t(watching === "approved" ? "join.watchAsk" : "join.watch")}
      </label>
      {watching === "nobody" && <p className="hint">{t("join.noWatching")}</p>}
    </fieldset>
  );
}

type Parts = { roles: ReactNode; alert: ReactNode; busy: boolean };

/** Make an account with the invite (the default): a username, a password, a display name, a language and a role. */
function MakeAccount({
  language,
  onLanguage,
  roles,
  alert,
  busy,
  onMake,
}: Parts & {
  language: string;
  onLanguage: (language: string) => void;
  onMake: (account: { username: string; password: string; display_name: string; language: string }) => void;
}) {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [other, setOther] = useState("");
  const code = language === OTHER ? other.trim().toLowerCase() : language;
  const ready = username.trim().length > 0 && password.length > 0 && name.trim().length > 0 && CODE.test(code);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ready && !busy) onMake({ username: username.trim(), password, display_name: name.trim(), language: code });
  }

  return (
    <form className="join-form" id="join-panel-make" role="tabpanel" aria-labelledby="join-tab-make" onSubmit={submit}>
      <label htmlFor="join-username">{t("join.username")}</label>
      <input
        id="join-username"
        data-testid="join-username"
        value={username}
        maxLength={32}
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        onChange={(e) => setUsername(e.target.value)}
      />
      <label htmlFor="join-password">{t("join.password")}</label>
      <input
        id="join-password"
        data-testid="join-password"
        type="password"
        value={password}
        autoComplete="new-password"
        onChange={(e) => setPassword(e.target.value)}
      />
      <p className="hint">{t("join.passwordHint")}</p>
      <label htmlFor="join-name">{t("join.displayName")}</label>
      <input
        id="join-name"
        data-testid="join-name"
        value={name}
        maxLength={40}
        autoComplete="nickname"
        onChange={(e) => setName(e.target.value)}
      />
      <label htmlFor="join-language">{t("join.language")}</label>
      <select id="join-language" data-testid="join-language" value={language} onChange={(e) => onLanguage(e.target.value)}>
        {LANGUAGES.map((lang) => (
          <option key={lang} value={lang}>
            {t(`language.${lang}`)}
          </option>
        ))}
        <option value={OTHER}>{t("join.lang.other")}</option>
      </select>
      {language === OTHER && (
        <>
          <label htmlFor="join-other-language">{t("join.otherCode")}</label>
          <input
            id="join-other-language"
            data-testid="join-other-language"
            value={other}
            maxLength={3}
            autoComplete="off"
            onChange={(e) => setOther(e.target.value)}
          />
          <p className="hint">{t("join.otherHint")}</p>
        </>
      )}
      {roles}
      {alert}
      <button type="submit" className="primary" data-testid="join-submit" disabled={!ready || busy}>
        {t("join.submit")}
      </button>
      {!ready && <p className="hint">{t("join.fillIn")}</p>}
    </form>
  );
}

/** Log in to an account first; the role step follows. */
function LogIn({ alert, busy, onLogIn }: Omit<Parts, "roles"> & { onLogIn: (username: string, password: string) => void }) {
  const t = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const ready = username.trim().length > 0 && password.length > 0;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (ready && !busy) onLogIn(username, password);
  }

  return (
    <>
      <form className="join-form" id="join-panel-login" role="tabpanel" aria-labelledby="join-tab-login" onSubmit={submit}>
        <label htmlFor="join-login-username">{t("join.username")}</label>
        <input
          id="join-login-username"
          data-testid="join-login-username"
          value={username}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          onChange={(e) => setUsername(e.target.value)}
        />
        <label htmlFor="join-login-password">{t("join.password")}</label>
        <input
          id="join-login-password"
          data-testid="join-login-password"
          type="password"
          value={password}
          autoComplete="current-password"
          onChange={(e) => setPassword(e.target.value)}
        />
        {alert}
        <button type="submit" className="primary" data-testid="join-login-submit" disabled={!ready || busy}>
          {t("login.submit")}
        </button>
      </form>
      <ForgotPassword />
    </>
  );
}

/** Who is logged in (players and tavern Task G3): "You are Ana" with Ana's avatar, and Not you? Log out. */
function YouAre({ profile, onLogOut }: { profile: ProfileSummary; onLogOut: () => void }) {
  const t = useT();
  return (
    <div className="join-you">
      <Avatar profile={profile} size={40} />
      <p>
        <span className="join-you-name">{t("join.youAre", { name: profile.display_name })}</span>
        <button type="button" className="link-button" data-testid="join-not-you" onClick={onLogOut}>
          {t("join.notYou")}
        </button>
      </p>
    </div>
  );
}

/** A logged-in account without a seat here: the role, and a name at this table (the display name unless given). */
function SeatForm({
  displayName,
  roles,
  alert,
  busy,
  onJoin,
}: Parts & { displayName: string; onJoin: (name: string) => void }) {
  const t = useT();
  const [name, setName] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!busy) onJoin(name.trim());
  }

  return (
    <form className="join-form" onSubmit={submit}>
      <label htmlFor="join-name">{t("join.name")}</label>
      <input
        id="join-name"
        data-testid="join-name"
        value={name}
        maxLength={40}
        placeholder={displayName}
        autoComplete="nickname"
        onChange={(e) => setName(e.target.value)}
      />
      {roles}
      {alert}
      <button type="submit" className="primary" data-testid="join-submit" disabled={busy}>
        {t("join.submit")}
      </button>
    </form>
  );
}

/** A dead PC (DEL-190): at -10 hit points, or gone from the party as fallen. It shows, marked, and can't be picked. */
const fallen = (c: Character) => isDead(c) || c.state.conditions.includes("dead") || c.departure === "died";

/**
 * A new player's characters: the free PCs, or a request to the DM for a new one, as the first act. The play screen
 * opens it too, for a player who has none (`onDone` instead of going to the table, and `onCancel`). Before the host
 * starts the session the table can't act (DEL-254): the picker says so, and keeps the request for the player's box
 * under the story (`holdRequest`) instead of sending it to be refused; a refusal that comes anyway keeps it too.
 */
export function PickCharacters({
  campaignId,
  onDone,
  onCancel,
}: {
  campaignId: string;
  onDone?: () => void;
  onCancel?: () => void;
}) {
  const t = useT();
  const navigate = useNavigate();
  const characters = useQuery({ queryKey: ["join", campaignId, "characters"], queryFn: () => listCharacters(campaignId) });
  const seats = useQuery({ queryKey: ["join", campaignId, "seats"], queryFn: () => getSeats(campaignId) });
  const state = useQuery({ queryKey: playKeys.state(campaignId), queryFn: () => getPlayState(campaignId) });
  const table = state.data?.table;
  const waits = table !== undefined && table.state !== "playing" && !table.solo;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [request, setRequest] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const played = new Set((seats.data ?? []).flatMap((s) => s.characters));
  const open = (characters.data ?? []).filter(hasSheet).filter((c) => c.kind === "pc" && !played.has(c.id));
  // The fallen show last, marked and not to be picked: the server refuses them too.
  const free = [...open.filter((c) => !fallen(c)), ...open.filter(fallen)];
  const claimable = free.filter((c) => !fallen(c)).length;

  function toggle(id: string) {
    setPicked((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function start() {
    setBusy(true);
    setError(null);
    try {
      for (const id of picked) await claimCharacter(campaignId, id);
      const words = request.trim();
      if (words && waits) holdRequest(campaignId, words);
      else if (words) {
        try {
          await act(campaignId, words);
        } catch (refused) {
          // The host hadn't started after all, or took a break meanwhile: the words wait in the box, not lost.
          if (!(refused instanceof ApiError && refused.status === 409)) throw refused;
          holdRequest(campaignId, words);
        }
      }
      if (onDone) onDone();
      else navigate(`/play/${encodeURIComponent(campaignId)}`, { replace: true });
    } catch (failed) {
      setError((failed as Error).message);
      setBusy(false);
    }
  }

  return (
    <main className="gate join">
      <div className="gate-card">
        <h1>{t("join.pick")}</h1>
        {(characters.isPending || seats.isPending) && <p className="placeholder">{t("join.loading")}</p>}
        {characters.data && seats.data && claimable === 0 && <p className="placeholder">{t("join.noneFree")}</p>}
        {free.length > 0 && (
          <ul className="join-characters">
            {free.map((c) => (
              <li key={c.id} className={fallen(c) ? "fallen" : undefined}>
                <input
                  type="checkbox"
                  id={`join-character-${c.id}`}
                  data-testid={`join-character-${c.id}`}
                  checked={picked.has(c.id)}
                  disabled={fallen(c)}
                  onChange={() => toggle(c.id)}
                />
                <label htmlFor={`join-character-${c.id}`}>
                  <span className="join-character-name">{c.name}</span>
                  <span className="row-meta">{[term(t, "race", c.sheet.race), classTerms(t, c.sheet.cls)].filter(Boolean).join(" ")}</span>
                  {fallen(c) && <span className="tag">{t("join.fallen")}</span>}
                </label>
              </li>
            ))}
          </ul>
        )}
        <label htmlFor="join-make-one">{t("join.makeOne")}</label>
        <textarea
          id="join-make-one"
          data-testid="join-make-one"
          rows={2}
          value={request}
          placeholder={t("join.makeOnePlaceholder")}
          onChange={(e) => setRequest(e.target.value)}
          aria-describedby={waits ? "join-make-one-waits" : undefined}
        />
        {waits && (
          <p id="join-make-one-waits" className="hint">
            {t("join.makeOneWaits")}
          </p>
        )}
        {error && (
          <p className="notice error" role="alert">
            {error}
          </p>
        )}
        <button type="button" className="primary" data-testid="join-play" disabled={busy} onClick={() => void start()}>
          {t("join.start")}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={busy}>
            {t("dialog.cancel")}
          </button>
        )}
      </div>
    </main>
  );
}
