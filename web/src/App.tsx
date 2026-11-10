import { MutationCache, QueryCache, QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { Navigate, Outlet, RouterProvider, createBrowserRouter, matchPath, useLocation, type RouteObject } from "react-router-dom";
import AppError from "./AppError";
import KeepSeat from "./account/KeepSeat";
import Login, { LoginRoot } from "./account/Login";
import { PrivacyRoot, TermsRoot } from "./account/Legal";
import { HelpIndex, HelpTopicPage } from "./help/HelpPages";
import { HelpPanel } from "./help/HelpPanel";
import { TourProvider } from "./help/tour";
import type { Audience } from "./help/topics";
import { LandingRoot } from "./landing/Landing";
import { SignUpRoot } from "./account/SignUp";
import { SetPasswordRoot } from "./account/SetPassword";
import { ConfirmEmailRoot } from "./mail/ConfirmEmail";
import { MailOffRoot } from "./mail/MailOff";
import MyTables from "./account/MyTables";
import FindTables from "./account/FindTables";
import { accountKeys, isOrganiser, type Me } from "./account/api";
import { useMe } from "./account/useMe";
import { ApiError, EventsContext, NeedsToken, getPreferences, queryKeys, sharedEvents, type Subscribe } from "./api";
import { AlertsProvider, SystemAlerts, useSystemAlert } from "./components/alerts";
import { DialogsProvider } from "./components/dialogs";
import Nav from "./components/Nav";
import { NavMenuContext } from "./components/navMenu";
import Desktop from "./desktop/Desktop";
import Toasts from "./components/Toasts";
import { I18nProvider, useT } from "./i18n";
import { JoinRoot } from "./routes/Join";
import Play from "./routes/Play";
import { rulesetKeys } from "./rulesets/api";
import { settingKeys } from "./setting/api";

type Router = ReturnType<typeof createBrowserRouter>;

/** A screen whose code loads when it is first opened (DEL-240): the organiser's screens, the print views, the novels,
 * the rulesets and the preferences. The router waits for it, showing the screen before, and a stale build's missing
 * chunk goes to `AppError`, which reloads. Play, joining and a player's tables stay in the main bundle: a player on a
 * phone opens them first. */
function later(load: () => Promise<ComponentType>): RouteObject["lazy"] {
  return async () => ({ Component: await load() });
}

/**
 * Every screen. A data router (createBrowserRouter, createMemoryRouter in tests)
 * rather than <BrowserRouter>, because the map editor's useBlocker needs one.
 * The editor and the print view are screens of their own, without the nav.
 * The front page (`/`, DEL-144), the help pages (DEL-145), the board (DEL-297), joining a table, a one-time account
 * link, the login page and the privacy policy and terms (DEL-208) are outside the app: they need no login. The app's own home is `/home`.
 */
const screens: RouteObject[] = [
  { path: "/", element: <LandingRoot /> },
  { path: "/help", element: <HelpIndex /> },
  { path: "/help/:slug", element: <HelpTopicPage /> },
  // The message board (DEL-297): public as the help is, for the zones open to everybody; its code loads when opened.
  {
    path: "/board",
    lazy: later(async () => (await import("./board/BoardFrame")).default),
    children: [
      { index: true, lazy: later(async () => (await import("./board/BoardIndex")).default) },
      { path: ":zoneId", lazy: later(async () => (await import("./board/ZonePage")).default) },
      { path: ":zoneId/:topicId", lazy: later(async () => (await import("./board/TopicPage")).default) },
    ],
  },
  { path: "/join/:token", element: <JoinRoot /> },
  { path: "/account/link/:token", element: <SetPasswordRoot /> },
  // An email's links (DEL-314): confirming an address and turning a kind of mail off need no login either.
  { path: "/account/email/:token", element: <ConfirmEmailRoot /> },
  { path: "/mail/off/:token", element: <MailOffRoot /> },
  { path: "/login", element: <LoginRoot /> },
  { path: "/sign-up", element: <SignUpRoot /> },
  { path: "/privacy", element: <PrivacyRoot /> },
  { path: "/terms", element: <TermsRoot /> },
  {
    element: <Root />,
    children: [
      {
        element: <Shell />,
        children: [
          { path: "/home", element: <Home /> },
          { path: "/tables", element: <MyTables /> },
          { path: "/tables/find", element: <FindTables /> },
          { path: "/play", element: <Play /> },
          { path: "/play/:campaignId", element: <Play /> },
          { path: "/campaigns", lazy: later(async () => (await import("./routes/Campaigns")).default) },
          { path: "/campaigns/:id", lazy: later(async () => (await import("./routes/CampaignDetail")).default) },
          { path: "/modules", lazy: later(async () => (await import("./routes/Modules")).default) },
          { path: "/modules/new", lazy: later(async () => (await import("./routes/NewModule")).default) },
          { path: "/modules/:moduleId", lazy: later(async () => (await import("./routes/ModuleDetail")).default) },
          { path: "/maps", lazy: later(async () => (await import("./routes/Maps")).default) },
          { path: "/maps/:moduleId", lazy: later(async () => (await import("./routes/Maps")).ModuleMaps) },
          { path: "/house-rules", lazy: later(async () => (await import("./routes/HouseRules")).default) },
          { path: "/settings", lazy: later(async () => (await import("./routes/Settings")).default) },
          { path: "/settings/:settingId", lazy: later(async () => (await import("./routes/SettingDetail")).default) },
          { path: "/settings/:settingId/pages/:title", lazy: later(async () => (await import("./routes/SettingPage")).default) },
          { path: "/settings/:settingId/new-page", lazy: later(async () => (await import("./routes/SettingPage")).NewSettingPage) },
          { path: "/rulesets", lazy: later(async () => (await import("./rulesets/Rulesets")).default) },
          { path: "/rulesets/:rulesetId", lazy: later(async () => (await import("./rulesets/RulesetPage")).default) },
          { path: "/rulesets/:rulesetId/:section", lazy: later(async () => (await import("./rulesets/SectionPage")).default) },
          { path: "/rulesets/:rulesetId/:section/:entryId", lazy: later(async () => (await import("./rulesets/EntryPage")).default) },
          { path: "/preferences", lazy: later(async () => (await import("./routes/Preferences")).default) },
          { path: "/preferences/players", lazy: later(async () => (await import("./account/Players")).default) },
          { path: "/novels/:id", lazy: later(async () => (await import("./novels/NovelReader")).default) },
          { path: "*", element: <Home /> },
        ],
      },
      // Monaco is large, so the editor loads when it is opened.
      { path: "/maps/:moduleId/:mapName", lazy: async () => ({ Component: (await import("./routes/MapEditor")).default }) },
      {
        path: "/campaigns/:campaignId/own-maps/:mapName",
        lazy: async () => ({ Component: (await import("./routes/MapEditor")).default }),
      },
      { path: "/maps/:moduleId/:mapName/print", lazy: later(async () => (await import("./routes/MapPrint")).default) },
      // Leaflet and Geoman are large too: the world-map screens load when one is opened.
      {
        path: "/world-maps/:owner/:ownerId/:name/*",
        lazy: async () => ({ Component: (await import("./worldmap/WorldMapRoutes")).default }),
      },
      { path: "/modules/:moduleId/print", lazy: later(async () => (await import("./routes/ModulePrint")).default) },
      { path: "/novels/:id/print", lazy: later(async () => (await import("./novels/NovelPrint")).default) },
      { path: "/campaigns/:campaignId/log", lazy: later(async () => (await import("./play/CampaignLog")).default) },
    ],
  },
];

/** The screens, each failing to `AppError` rather than the router's own page (a stale build reloads itself). */
export const routes: RouteObject[] = screens.map((route) => ({ ...route, errorElement: <AppError /> }));

export function createRouter(): Router {
  return createBrowserRouter(routes);
}

/** `router` is the caller's in tests (createMemoryRouter(routes)); the browser's otherwise. */
export default function App({ router }: { router?: Router }) {
  const [active] = useState(() => router ?? createRouter());
  return <RouterProvider router={active} />;
}

/** The query client, the interface language, Delve's dialogs, the event stream and the login page, around every
 * screen. The dialogs sit inside the language, which their Cancel button speaks. */
function Root() {
  const [needsToken, setNeedsToken] = useState(false);
  const [client] = useState(() => {
    // Any call answered with 401 swaps the whole app for the login page.
    const onError = (error: Error) => {
      if (error instanceof NeedsToken) setNeedsToken(true);
    };
    return new QueryClient({
      queryCache: new QueryCache({ onError }),
      mutationCache: new MutationCache({ onError }),
      defaultOptions: {
        queries: {
          // Only network failures are worth retrying; the server's answers stand.
          retry: (count, error) => !(error instanceof NeedsToken || error instanceof ApiError) && count < 2,
          refetchOnWindowFocus: false,
        },
      },
    });
  });
  return (
    <QueryClientProvider client={client}>
      <Language>
        <DialogsProvider>
          <AlertsProvider>{needsToken ? <Login /> : <Events />}</AlertsProvider>
        </DialogsProvider>
      </Language>
    </QueryClientProvider>
  );
}

/** A player's account (not an organiser): it reaches its tables, their play screens, Preferences and the Rulesets
 * area, and nothing of the organiser's (players and tavern Task E3). */
function isPlayerAccount(me: Me | undefined): boolean {
  return Boolean(me?.account && !isOrganiser(me.account));
}

/** Whose help topics the "?" panel shows (DEL-145): the owner's (the owner token, this machine or an owner account),
 * an organiser's, or a player's (a player's account, a seat). */
function helpRole(me: Me | undefined): Audience {
  if (me?.account) return me.account.owner ? "owner" : isOrganiser(me.account) ? "organiser" : "player";
  if (me?.seat) return "player";
  return me?.principal?.id === "owner" ? "owner" : "player";
}

/** The campaign of a play screen's address, or null elsewhere. */
function playCampaign(pathname: string): string | null {
  return matchPath("/play/:campaignId", pathname)?.params.campaignId ?? null;
}

/** `/home` and every unknown address: My tables for a player's account, the campaigns for anyone else. */
function Home() {
  const me = useMe();
  if (me.isPending) return null;
  return <Navigate to={isPlayerAccount(me.data) ? "/tables" : "/campaigns"} replace />;
}

function Language({ children }: { children: ReactNode }) {
  // The interface language comes from the preferences, and is English until they load; a seat's and an account's are
  // their own, and neither asks for the preferences (a seat, or a player's account, may not read them).
  const me = useMe();
  const seat = me.data?.seat;
  const account = me.data?.account;
  const preferences = useQuery({
    queryKey: queryKeys.preferences,
    queryFn: getPreferences,
    enabled: !me.isPending && !seat && !account,
  });
  const language = account ? account.language : seat ? seat.language : preferences.data?.language;
  return <I18nProvider language={language}>{children}</I18nProvider>;
}

/** The app's one event stream, which the screens listen to through `EventsContext`; it re-fetches what the server
 * says has changed. A seat's browser listens only at its table: a seat is present while it listens, and the Rulesets
 * area in another tab mustn't keep it present after the play tab is closed. A player's account listens only on a play
 * screen too. An account's stream names the table it listens at (`?campaign=`), without which it hears no table's
 * events; an organiser's account hears the organisers' events on every screen. */
function Events() {
  const client = useQueryClient();
  const t = useT();
  const me = useMe();
  const { pathname } = useLocation();
  const atTable = pathname.startsWith("/play/");
  const onlyAtTable = Boolean(me.data?.seat) || isPlayerAccount(me.data);
  const listening = !me.isPending && (!onlyAtTable || atTable);
  const campaign = me.data?.account ? playCampaign(pathname) : null;
  // A new stream for another table: the server decides once, when it opens, what it delivers.
  const events = useMemo(() => sharedEvents(campaign), [campaign]);
  // The stream closed and Delve no longer knows this browser (a seat removed, the token changed, an account's login
  // ended): an account is told to reload or log in again, a seat to open its table's link again.
  const [lost, setLost] = useState(false);
  useEffect(() => {
    if (!listening) return;
    const stopLost = events.onLost(() => setLost(true));
    const unsubscribe = events.subscribe({
      // The preferences changed, or a connection did (a provider came or went): both are fetched again.
      preferences: () => {
        client.invalidateQueries({ queryKey: queryKeys.preferences });
        client.invalidateQueries({ queryKey: queryKeys.backends });
      },
      // An account changed, or a sign-up came or was decided (DEL-156): the Players page and the menu's count again.
      accounts: () => {
        client.invalidateQueries({ queryKey: accountKeys.accounts });
        client.invalidateQueries({ queryKey: accountKeys.signUp });
      },
      // A campaign's status changed (plan 7 Task 19): the campaigns list is fetched again.
      campaigns: () => client.invalidateQueries({ queryKey: queryKeys.campaigns }),
      modules: (data) => {
        client.invalidateQueries({ queryKey: queryKeys.modules });
        if ((data as { categories?: unknown } | null)?.categories) client.invalidateQueries({ queryKey: queryKeys.moduleCategories });
        const id = (data as { id?: unknown } | null)?.id;
        // Exact: an open editor's map isn't re-fetched under its unsaved changes.
        if (typeof id === "string") {
          client.invalidateQueries({ queryKey: queryKeys.module(id), exact: true });
          client.invalidateQueries({ queryKey: queryKeys.moduleMetadata(id), exact: true });
        }
      },
      // A map state changed: its state and both views are fetched again.
      map_state: (data) => {
        const { campaign_id, map } = (data ?? {}) as { campaign_id?: unknown; map?: unknown };
        if (typeof campaign_id === "string" && typeof map === "string")
          client.invalidateQueries({ queryKey: queryKeys.mapState(campaign_id, map) });
      },
      // A rule, a bundle or a campaign's choice changed: every house-rules query is fetched again, and every rulesets
      // query, whose homebrew items, classes and races are the campaign's house rules.
      house_rules: () => {
        client.invalidateQueries({ queryKey: queryKeys.houseRules });
        client.invalidateQueries({ queryKey: rulesetKeys.list });
      },
      characters: (data) => {
        const campaignId = (data as { campaign_id?: unknown } | null)?.campaign_id;
        if (typeof campaignId === "string") client.invalidateQueries({ queryKey: queryKeys.characters(campaignId) });
      },
      // A setting's pages, facts, proposals or maps changed: every query of that setting is fetched again.
      setting: (data) => {
        const id = (data as { id?: unknown } | null)?.id;
        if (typeof id === "string") client.invalidateQueries({ queryKey: settingKeys.one(id) });
      },
      // The world changed (plan 6): the play screen's world and the campaign page's tables are fetched again.
      world: (data) => {
        const campaignId = (data as { campaign_id?: unknown } | null)?.campaign_id;
        if (typeof campaignId === "string") client.invalidateQueries({ queryKey: ["campaign", campaignId, "world"] });
      },
      // A DM's tool call, told once for all it may have changed (DEL-168): the characters, each map's state and views,
      // and the world, as their own events would.
      changed: (data) => {
        const { campaign_id, areas, maps } = (data ?? {}) as { campaign_id?: unknown; areas?: unknown; maps?: unknown };
        if (typeof campaign_id !== "string" || !Array.isArray(areas)) return;
        if (areas.includes("characters")) client.invalidateQueries({ queryKey: queryKeys.characters(campaign_id) });
        if (areas.includes("map_state") && Array.isArray(maps))
          for (const map of maps)
            if (typeof map === "string") client.invalidateQueries({ queryKey: queryKeys.mapState(campaign_id, map) });
        if (areas.includes("world")) client.invalidateQueries({ queryKey: ["campaign", campaign_id, "world"] });
      },
    });
    return () => {
      stopLost();
      unsubscribe();
      events.close();
    };
  }, [client, events, listening]);
  // Delve no longer knows this browser: a system alert that stays until the page is reloaded.
  useSystemAlert(
    lost
      ? {
          id: "events-lost",
          tone: "error",
          text: t(me.data?.account ? "events.lost_account" : "events.lost"),
          dismissible: false,
          action: { label: t("events.reload"), onClick: () => window.location.reload() },
        }
      : null,
  );
  return (
    <EventsContext.Provider value={listening ? events.subscribe : notListening}>
      <SystemAlerts pageWide />
      <SeatsStayAtTheirTable />
    </EventsContext.Provider>
  );
}

// What a screen subscribes to while the stream is shut: nothing opens it.
const notListening: Subscribe = () => () => {};

/** A seat's browser shows only the Play screen of its campaign, its log (DEL-324), and the Rulesets area (which the
 * play header opens in a new tab); a player's account its tables, their play screens and logs, Preferences and the
 * Rulesets area. The screens wait to know who this is. */
function SeatsStayAtTheirTable() {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return null;
  const seat = me.data?.seat;
  const table = seat ? `/play/${encodeURIComponent(seat.campaign_id)}` : null;
  const rulesets = location.pathname === "/rulesets" || location.pathname.startsWith("/rulesets/");
  const ownLog = seat ? location.pathname === `/campaigns/${encodeURIComponent(seat.campaign_id)}/log` : false;
  if (table && location.pathname !== table && !rulesets && !ownLog) return <Navigate to={table} replace />;
  if (isPlayerAccount(me.data) && !rulesets && !playerMayOpen(location.pathname)) return <Navigate to="/tables" replace />;
  return <Outlet />;
}

function playerMayOpen(pathname: string): boolean {
  return (
    pathname === "/tables" ||
    pathname === "/tables/find" ||
    pathname === "/preferences" ||
    playCampaign(pathname) !== null ||
    /^\/campaigns\/[^/]+\/log$/.test(pathname)
  );
}

function Shell() {
  // A seat has no nav: there is nowhere else for it to go but the Rulesets area, which has its own way back.
  const me = useMe().data;
  const seated = Boolean(me?.seat);
  const t = useT();
  const { pathname } = useLocation();
  const campaign = me?.account ? playCampaign(pathname) : null;
  const role = seated ? "player" : helpRole(me);
  // The phone's whole nav as a sheet (DEL-188), opened from the bar's More or the play screen's Menu.
  const [menuOpen, setMenuOpen] = useState(false);
  const menu = useMemo(() => (seated ? null : { open: menuOpen, setOpen: setMenuOpen }), [seated, menuOpen]);
  return (
    <TourProvider role={role}>
      <NavMenuContext.Provider value={menu}>
      <div className={seated ? "shell seated" : "shell"}>
        <a
          className="skip-link"
          href="#content"
          onClick={(event) => {
            // Focus the content itself, without a hash in the address that the router would see.
            event.preventDefault();
            document.getElementById("content")?.focus();
          }}
        >
          {t("app.skipToContent")}
        </a>
        {!seated && <Nav account={me?.account ?? null} help={<HelpPanel role={role} place="nav" />} />}
        <main className="content" id="content" tabIndex={-1}>
          <SystemAlerts />
          {campaign && <KeepSeat campaignId={campaign} />}
          <Outlet />
        </main>
        <Desktop owner={!seated && !isPlayerAccount(me)} />
        {seated && <HelpPanel role="player" place="corner" />}
        <Toasts />
      </div>
      </NavMenuContext.Provider>
    </TourProvider>
  );
}
