// The account routes (players and tavern Tasks C4–C6): logging in, the account's logins and password, one-time
// links, its tables, joining by invite, and the organiser's Players API.
import { apiFetch, deleteJson, postJson, putJson, type CampaignStatus, type NextSession, type Schedule } from "../api";
import type { Seat, SeatRole } from "../play/api";
import type { ProfileSummary } from "../profile/api";
import type { TablePerson } from "../profile/TableFaces";

/** The logged-in account, as `/api/me` and the login routes answer it. */
export interface Account {
  id: string;
  username: string;
  display_name: string;
  language: string;
  organiser: boolean;
  owner: boolean;
}

/** Whether an account organises: an organiser, or the owner, whom the server treats as one (DEL-158). */
export function isOrganiser(account: Account): boolean {
  return account.organiser || account.owner;
}

/** Who this browser is, as `GET /api/me` answers: the owner, an account, or a seat token; `seat` is the seat at the
 * asked campaign (`?campaign=`), or a seat token's own. `keepable_seat` is an old seat token's seat at the asked
 * campaign that the account may keep. `owner_account_exists` is said only to this machine. The play screen's tests
 * leave `account` and `keepable_seat` out, as an older server did. */
export interface Me {
  principal: { id: string; roles: string[] };
  seat: {
    id: string;
    campaign_id: string;
    campaign_name: string;
    name: string;
    language: string;
    role: SeatRole;
    organiser: boolean;
  } | null;
  account?: Account | null;
  keepable_seat?: { id: string; name: string } | null;
  owner_account_exists?: boolean;
}

/** One browser the account is logged in on. */
export interface LoginSession {
  id: string;
  device: string;
  last_used_at: string;
  current: boolean;
}

export interface AccountLink {
  username: string;
  kind: "set-password" | "reset-password";
}

/** A table the account has a live seat at. */
export interface MyTable {
  /** The table's next sessions on its schedule (DEL-204 part C); left out by an older server. */
  next_sessions?: NextSession[];
  campaign_id: string;
  name: string;
  module_title: string;
  /** The campaign's status: a complete one is shown grayed, last; left out by an older server. */
  status?: CampaignStatus;
  role: SeatRole;
  /** Its places for players and how many are taken, and who sits at it (DEL-217); left out by an older server. */
  slots?: number | null;
  taken?: number;
  people?: TablePerson[];
  seat_id: string;
  last_played_at: string | null;
  session_number: number;
  banner: boolean;
}

/** An account as the Players page lists it. */
export interface PlayerAccount {
  id: string;
  username: string;
  display_name: string;
  organiser: boolean;
  owner: boolean;
  disabled: boolean;
  has_password: boolean;
  /** Whether it has a confirmed email address (DEL-314); the address itself is the account's alone. */
  has_email: boolean;
  created_at: string;
  tables: number;
  /** A sign-up that waits for approval (DEL-156), with what it told the approver. */
  pending: boolean;
  request_note: string;
  /** When the player asked for a new password on the login page, while that request is open (DEL-268). */
  reset_asked_at?: string | null;
}

export interface OneTimeLink {
  url: string;
  expires_at: string;
}

export type JoinRole = "player" | "observer";

export const accountKeys = {
  me: (campaign?: string) => (campaign ? ["me", campaign] : ["me"]),
  sessions: ["account", "sessions"] as const,
  tables: ["account", "tables"] as const,
  /** The public tables to find (DEL-204), and the account's requests to join them. */
  findTables: ["tables", "public"] as const,
  requests: ["account", "requests"] as const,
  /** A table's requests to join, as its host and co-hosts read them. */
  tableRequests: (campaignId: string) => ["campaign", campaignId, "requests"] as const,
  accounts: ["accounts"] as const,
  signUp: ["sign-up"] as const,
  link: (token: string) => ["account-link", token] as const,
  authProviders: ["auth", "providers"] as const,
  identities: ["account", "identities"] as const,
};

export const getMe = (campaign?: string) =>
  apiFetch<Me>(campaign ? `/api/me?campaign=${encodeURIComponent(campaign)}` : "/api/me");

/** `joinToken`: logging in on a table's join page, which lets a sign-up that waits for approval in (DEL-156). */
export const logIn = (username: string, password: string, joinToken?: string) =>
  postJson<{ account: Account }>("/api/login", { username, password, ...(joinToken ? { join_token: joinToken } : {}) }).then(
    (answer) => answer.account,
  );
export const logOut = () => postJson<unknown>("/api/logout");
/** The install's first owner account, from this machine while there is none. */
export const makeFirstOwner = (username: string, password: string) =>
  postJson<{ account: Account }>("/api/accounts/first-owner", { username, password }).then((answer) => answer.account);

export const getSessions = () => apiFetch<LoginSession[]>("/api/account/sessions");
export const endSession = (id: string) => deleteJson<unknown>(`/api/account/sessions/${encodeURIComponent(id)}`);
export const endAllSessions = () => postJson<unknown>("/api/account/sessions/end-all");
export const changePassword = (old: string, next: string) => putJson<unknown>("/api/account/password", { old, new: next });

const linkPath = (token: string) => `/api/account-links/${encodeURIComponent(token)}`;
export const getLink = (token: string) => apiFetch<AccountLink>(linkPath(token));
export const useLink = (token: string, password: string) =>
  postJson<{ account: Account }>(linkPath(token), { password }).then((answer) => answer.account);

export const getMyTables = () => apiFetch<MyTable[]>("/api/account/tables");

/** A message on a request to join (DEL-204): the player's or a host's, by name. */
export interface RequestMessage {
  from: "player" | "host";
  name: string;
  text: string;
  at: string;
}

export type RequestStatus = "pending" | "accepted" | "declined" | "withdrawn";

/** An account's request to join a public table: its thread with the hosts while it waits, then accepted (with the
 * seat it made) or declined, or withdrawn by the player. */
export interface JoinRequest {
  id: string;
  campaign_id: string;
  status: RequestStatus;
  messages: RequestMessage[];
  created_at: string;
  decided_at: string | null;
  seat_id: string | null;
  /** To play, or to watch at a table whose watchers a host lets in (DEL-215); an older server leaves it out. */
  role?: "player" | "observer";
  account: { id: string; display_name: string; profile: ProfileSummary | null };
  /** In the account's own list: the table it asks to join. */
  campaign?: { id: string; name: string; module_title: string };
}

/** A public table as Find a table lists it. */
export interface PublicTable {
  campaign_id: string;
  name: string;
  module_title: string;
  ruleset: string;
  setting: string | null;
  /** The ruleset's and the setting's titles, to show (the ids above are for links). */
  ruleset_title?: string;
  setting_title?: string | null;
  description: string;
  slots: number | null;
  /** Who may watch (DEL-215); an older server leaves it out. */
  observers?: "anyone" | "approved" | "nobody";
  taken: number;
  full: boolean;
  house_rules: { id: string; title: string; body_md: string }[];
  /** Null only for a table with no live host seat. */
  host: { display_name: string; profile: ProfileSummary | null } | null;
  /** Who sits at the table (DEL-217); left out by an older server. */
  people?: TablePerson[];
  schedule?: Schedule | null;
  next_sessions?: NextSession[];
  seated: boolean;
  request: { id: string; status: RequestStatus } | null;
}

/** As the server takes them: a note or a message of at most this many characters. */
export const MESSAGE_CHARS = 1000;

export const listPublicTables = () => apiFetch<PublicTable[]>("/api/tables");
/** Ask to join a public table, as a player, or with `observer` to watch (DEL-215). */
export const askToJoin = (campaignId: string, note: string, role: "player" | "observer" = "player") =>
  postJson<{ request: JoinRequest }>(`/api/tables/${encodeURIComponent(campaignId)}/requests`, { note, role });
export const getMyRequests = () => apiFetch<JoinRequest[]>("/api/account/requests");
export const sendRequestMessage = (id: string, text: string) =>
  postJson<{ request: JoinRequest }>(`/api/requests/${encodeURIComponent(id)}/messages`, { text });
export const withdrawRequest = (id: string) => postJson<{ request: JoinRequest }>(`/api/requests/${encodeURIComponent(id)}/withdraw`);

const requestsPath = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}/requests`;
export const getTableRequests = (campaignId: string) => apiFetch<JoinRequest[]>(requestsPath(campaignId));
export const acceptRequest = (campaignId: string, id: string) =>
  postJson<{ request: JoinRequest }>(`${requestsPath(campaignId)}/${encodeURIComponent(id)}/accept`);
export const declineRequest = (campaignId: string, id: string, reason: string) =>
  postJson<{ request: JoinRequest }>(`${requestsPath(campaignId)}/${encodeURIComponent(id)}/decline`, { reason });

const joinPath = (token: string) => `/api/join/${encodeURIComponent(token)}`;
/** A seat at the table, or, to watch where a host lets watchers in, the request it made instead (DEL-215). */
export type JoinAnswer = { campaign_id: string } & ({ seat: Seat; join_request?: never } | { seat?: never; join_request: JoinRequest });
export const joinAsAccount = (token: string, seat: { role: JoinRole; name?: string }) =>
  postJson<JoinAnswer>(joinPath(token), seat);
export const joinWithNewAccount = (
  token: string,
  account: { username: string; password: string; display_name: string; language: string; role: JoinRole },
) => postJson<JoinAnswer & { account: Account }>(`${joinPath(token)}/account`, account);

export const keepSeat = (campaignId: string) =>
  postJson<Seat>(`/api/campaigns/${encodeURIComponent(campaignId)}/seats/keep`);

export const listAccounts = () => apiFetch<PlayerAccount[]>("/api/accounts");
export const addAccount = (account: { username: string; display_name?: string; language?: string }) =>
  postJson<{ account: PlayerAccount; link: OneTimeLink }>("/api/accounts", account);
export const resetLink = (id: string) => postJson<OneTimeLink>(`/api/accounts/${encodeURIComponent(id)}/reset-link`);
export const changeAccount = (id: string, change: { disabled?: boolean; organiser?: boolean; owner?: boolean }) =>
  putJson<PlayerAccount>(`/api/accounts/${encodeURIComponent(id)}`, change);
export const approveAccount = (id: string) => postJson<PlayerAccount>(`/api/accounts/${encodeURIComponent(id)}/approve`);
export const rejectAccount = (id: string) => deleteJson<unknown>(`/api/accounts/${encodeURIComponent(id)}`);
/** A player's request for a new password (DEL-268): asked on the login page, dismissed on the Players page. While Delve
 * sends email (DEL-314) `nameOrAddress` may be an address, and a confirmed one gets the reset link by email. */
export const askPasswordHelp = (nameOrAddress: string) =>
  postJson<{ asked: boolean }>("/api/password-help", { username: nameOrAddress });
export const dismissResetRequest = (id: string) =>
  deleteJson<unknown>(`/api/accounts/${encodeURIComponent(id)}/reset-request`);

/** Sign-up with approval (DEL-156): whether it is open, opening or closing it (an organiser), and asking. */
export const getSignUp = () => apiFetch<{ open: boolean }>("/api/sign-up");
export const setSignUp = (open: boolean) => putJson<{ open: boolean }>("/api/sign-up", { open });
export const signUp = (ask: { username: string; password: string; display_name?: string; language: string; note?: string; email?: string }) =>
  postJson<{ username: string; pending: true }>("/api/sign-up", ask);

/** How many sign-ups wait for approval, and players for a new password (DEL-268), of the accounts the Players page
 * lists. */
export const pendingCount = (accounts: PlayerAccount[] | undefined) =>
  accounts?.filter((a) => a.pending || a.reset_asked_at).length ?? 0;

/** The logged-in account, as a join link's `GET` names it (null for anyone else), with its live seat there. */
export interface JoinYou {
  account_id: string;
  display_name: string;
  seat_id: string | null;
  /** Its profile summary, as a seat shows it. */
  profile: ProfileSummary;
}

/** An outside account Delve logs in with (DEL-206): a provider this browser may use. */
export interface AuthProvider {
  id: string;
  title: string;
}

/** An outside account linked to the account logged in; `email` is the one it had when it was linked. */
export interface LinkedIdentity {
  provider: string;
  title: string;
  email: string;
  linked_at: string;
}

export type OutsideMode = "login" | "link" | "signup";

export const getAuthProviders = () => apiFetch<AuthProvider[]>("/api/auth/providers");
/** The account's linked outside accounts, and whether it has a password (linking then asks for it). */
export const getIdentities = () =>
  apiFetch<{ identities: LinkedIdentity[]; has_password: boolean }>("/api/account/identities");
/** Linking's start (DEL-206): a URL with a ticket, for the account's password when it has one. */
export const linkTicket = (provider: string, password?: string) =>
  postJson<{ url: string }>(`/api/auth/${encodeURIComponent(provider)}/link`, password === undefined ? {} : { password });
export const unlinkIdentity = (provider: string) =>
  deleteJson<unknown>(`/api/account/identities/${encodeURIComponent(provider)}`);

/** Where a "Continue with …" button sends the browser: the provider's start, which sends it on to the provider. */
export function outsideStartUrl(provider: string, mode: OutsideMode, params: Record<string, string> = {}): string {
  const query = new URLSearchParams({ mode, ...Object.fromEntries(Object.entries(params).filter(([, v]) => v)) });
  return `/api/auth/${encodeURIComponent(provider)}/start?${query}`;
}
