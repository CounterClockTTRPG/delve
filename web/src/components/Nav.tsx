import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Languages, Menu, X } from "lucide-react";
import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { toast } from "sonner";
import { EventsContext, getPreferences, putPreferences, queryKeys, type ConversionEvent, type ConversionKind } from "../api";
import { LANGUAGES, isLanguage, useT, type Language, type MessageKey } from "../i18n";
import { accountKeys, isOrganiser, listAccounts, logOut, pendingCount, type Account } from "../account/api";
import { profileKeys, putProfile } from "../profile/api";
import "../account/account.css";
import { conversionLink, makesModule, markSeen, runningOf, useConversions } from "../module/conversions";
import { useNavMenu } from "./navMenu";

// A side bar from 900 px up, a bottom tab bar below (styles.css). A dot on Modules while a conversion runs, and a
// notice on any screen when one ends. The side bar's footer switches the interface language. An account has My tables
// and Log out too; a player's account has only My tables, the Board and Preferences (players and tavern Task E3).
//
// The phone's bar holds the first `ON_THE_BAR` areas and More (DEL-188): More opens the whole nav as a sheet, with every
// area, Help, the language and Log out. The play screen hides the bar and opens the sheet from its own Menu.

/** How many areas the phone's bar shows before More. */
const ON_THE_BAR = 4;

/** The message board (DEL-297), outside the app's shell, for every account. */
const BOARD = { to: "/board", label: "area.board" as MessageKey, icon: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5" };

export const AREAS: { to: string; label: MessageKey; icon: string }[] = [
  // Icon paths are 24×24 strokes.
  { to: "/play", label: "area.play", icon: "M5 19l7-14 7 14M8.5 12h7" },
  { to: "/campaigns", label: "area.campaigns", icon: "M6 4h9l3 3v13H6zM9 10h6M9 14h6" },
  { to: "/modules", label: "area.modules", icon: "M4 5h7v14H4zM13 5h7v14h-7z" },
  { to: "/maps", label: "area.maps", icon: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z" },
  { to: "/house-rules", label: "area.houseRules", icon: "M12 3l7 4v5c0 4-3 7-7 9-4-2-7-5-7-9V7z" },
  { to: "/rulesets", label: "rulesets.title", icon: "M6 4h11v16H8a2 2 0 01-2-2zM6 18a2 2 0 012-2h9M10 8h4" },
  { to: "/settings", label: "area.settings", icon: "M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18" },
  BOARD,
  { to: "/preferences", label: "area.preferences", icon: "M4 7h10M18 7h2M4 17h4M12 17h8M16 5v4M10 15v4" },
];

const MY_TABLES = { to: "/tables", label: "nav.myTables" as MessageKey, icon: "M3 10h18M6 10v9M18 10v9M8 6h8" };
/** Find a table (DEL-204): the public tables, for any logged-in account. */
const FIND_TABLE = { to: "/tables/find", label: "find.title" as MessageKey, icon: "M11 4a7 7 0 100 14 7 7 0 000-14zM20 20l-4-4" };
const LOG_OUT_ICON = "M10 5H5v14h5M14 8l4 4-4 4M18 12H9";

/** `account` is the logged-in account (null for the owner token, this machine or a seat token); `help` is the help's
 * button (DEL-145), last but for Log out. */
export default function Nav({ account = null, help = null }: { account?: Account | null; help?: React.ReactNode }) {
  if (account && !isOrganiser(account)) return <PlayerNav account={account} help={help} />;
  return <OrganiserNav account={account} help={help} />;
}

/** A player's account: its tables and its preferences, and nothing of the organiser's is asked for. */
function PlayerNav({ account, help }: { account: Account; help: React.ReactNode }) {
  const t = useT();
  const areas = [MY_TABLES, FIND_TABLE, BOARD, AREAS.find((area) => area.to === "/preferences")!];
  return (
    <NavFrame>
      <ul>
        {areas.map((area, index) => (
          <li key={area.to} className={onTheBar(index)}>
            <NavLink to={area.to} end={area.to === "/tables"}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d={area.icon} />
              </svg>
              <span>{t(area.label)}</span>
            </NavLink>
          </li>
        ))}
        <More />
        {help && <li className="nav-extra">{help}</li>}
        <LogOut />
      </ul>
      <LanguageSwitch account={account} />
    </NavFrame>
  );
}

function onTheBar(index: number): string | undefined {
  return index < ON_THE_BAR ? undefined : "nav-extra";
}

/** The nav, open on a phone as a sheet over a dimmed screen (`nav.menu-open`) while its menu is; a link followed, a
 * tap beside it or Escape closes it. */
function NavFrame({ children }: { children: ReactNode }) {
  const t = useT();
  const menu = useNavMenu();
  const { pathname } = useLocation();
  const open = menu?.open ?? false;
  const setOpen = menu?.setOpen;
  useEffect(() => setOpen?.(false), [pathname, setOpen]);
  useEffect(() => {
    if (!open || !setOpen) return;
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [open, setOpen]);
  return (
    <>
      {open && <div className="nav-backdrop" data-testid="nav-backdrop" onClick={() => setOpen?.(false)} />}
      <nav
        id="nav"
        className={open ? "nav menu-open" : "nav"}
        aria-label={t("nav.label")}
        // Help opens over the screen: the sheet closes under it.
        onClick={(event) => (event.target as Element).closest(".nav-help") && setOpen?.(false)}
      >
        <p className="wordmark" aria-hidden="true">
          {t("app.name")}
        </p>
        {children}
      </nav>
    </>
  );
}

/** The phone bar's More, Close while the sheet is open; the side bar has none. `notice`: an area under it carries a dot
 * or a count. */
function More({ notice = false }: { notice?: boolean }) {
  const t = useT();
  const menu = useNavMenu();
  if (!menu) return null;
  return (
    <li className="nav-more-item">
      <button
        type="button"
        className="nav-more"
        data-testid="nav-more"
        aria-expanded={menu.open}
        aria-controls="nav"
        onClick={() => menu.setOpen(!menu.open)}
      >
        {menu.open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        <span>{t(menu.open ? "nav.close" : "nav.more")}</span>
        {notice && !menu.open && <span className="nav-dot" aria-hidden="true" />}
      </button>
    </li>
  );
}

/** Log out, then the login page. */
function LogOut() {
  const t = useT();
  const [busy, setBusy] = useState(false);
  return (
    <li className="nav-extra">
      <button
        type="button"
        className="nav-logout"
        data-testid="nav-logout"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          void logOut()
            .catch(() => undefined)
            .then(() => window.location.assign("/"));
        }}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d={LOG_OUT_ICON} />
        </svg>
        <span>{t("nav.logout")}</span>
      </button>
    </li>
  );
}

function OrganiserNav({ account, help }: { account: Account | null; help: React.ReactNode }) {
  const t = useT();
  const conversions = useConversions();
  const converting = runningOf(conversions) !== null;
  // Sign-ups waiting for approval (DEL-156), on Preferences, where the Players page is. A seat token is refused the
  // list, and then shows none.
  const accounts = useQuery({ queryKey: accountKeys.accounts, queryFn: listAccounts, retry: false });
  const waiting = pendingCount(accounts.data);
  const areas = account ? [MY_TABLES, FIND_TABLE, ...AREAS] : AREAS;
  const noticed = (to: string) => (to === "/modules" && converting) || (to === "/preferences" && waiting > 0);
  return (
    <>
      <NavFrame>
        <ul>
          {areas.map((area, index) => (
            <li key={area.to} className={onTheBar(index)}>
              <NavLink to={area.to} end={area.to === "/tables"}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d={area.icon} />
                </svg>
                <span>{t(area.label)}</span>
                {area.to === "/modules" && converting && (
                  <span className="nav-dot" role="img" aria-label={t("nav.converting")} title={t("nav.converting")} />
                )}
                {area.to === "/preferences" && waiting > 0 && (
                  <span
                    className="nav-count"
                    data-testid="nav-waiting"
                    aria-label={t("nav.waiting", { count: String(waiting) })}
                    title={t("nav.waiting", { count: String(waiting) })}
                  >
                    {waiting}
                  </span>
                )}
              </NavLink>
            </li>
          ))}
          <More notice={areas.some((area, index) => index >= ON_THE_BAR && noticed(area.to))} />
          {help && <li className="nav-extra">{help}</li>}
          {account && <LogOut />}
        </ul>
        <LanguageSwitch account={account} />
      </NavFrame>
      <ConversionEnded />
    </>
  );
}

/**
 * The interface language, a menu in the side bar's footer (DEL-122). Logged in, it is the account's own language (its
 * profile's), which the interface speaks; for the owner's account the install's too, which the owner's seats and their
 * story follow. Without an account (the owner token) it saves only the preferences' `language`. The preferences'
 * choices aren't sent: GET answers them as they can be used now, and sending them back would save a default over a
 * stored choice.
 */
function LanguageSwitch({ account }: { account: Account | null }) {
  const t = useT();
  const client = useQueryClient();
  const preferences = useQuery({ queryKey: queryKeys.preferences, queryFn: getPreferences, enabled: !account });
  const save = useMutation({
    mutationFn: async (language: Language) => {
      if (account) await putProfile({ language });
      if (!account || account.owner) client.setQueryData(queryKeys.preferences, await putPreferences({ language }));
    },
    onSuccess: () => {
      // The interface reads its language from who is logged in; the owner's seats follow the install's: a play screen
      // reads its seat again, and its story in that language.
      void client.invalidateQueries({ queryKey: accountKeys.me() });
      void client.invalidateQueries({ queryKey: profileKeys.own });
    },
  });
  const current = account ? account.language : preferences.data?.language;
  const ready = account ? true : !!preferences.data;
  return (
    <div className="nav-footer">
      <Languages size={16} aria-hidden="true" />
      <select
        aria-label={t("nav.language")}
        value={current ?? ""}
        disabled={!ready || save.isPending}
        onChange={(e) => isLanguage(e.target.value) && e.target.value !== current && save.mutate(e.target.value)}
      >
        {!current && <option value="" />}
        {LANGUAGES.map((lang) => (
          <option key={lang} value={lang}>
            {t(`language.${lang}`)}
          </option>
        ))}
      </select>
    </div>
  );
}

// What the end notice's link opens, by the conversion's kind (`conversionLink`).
const LINK_LABELS: Record<ConversionKind, string> = {
  pdf: "conversion.open",
  generate: "conversion.open",
  worldmap: "conversion.openReview",
  "dungeon-map": "conversion.openDrafts",
  "book-map": "conversion.openDrafts",
  novel: "conversion.openNovel",
  history: "conversion.openHistory",
  fixit: "conversion.open",
};

/**
 * The end of a conversion heard on this screen, as a notification in the corner (sonner, components/Toasts.tsx): what
 * it made, with a link to it, or why it failed. A failure stays until it is closed. New module shows the end itself, so
 * an end heard there makes no notification.
 */
function ConversionEnded() {
  const t = useT();
  const subscribe = useContext(EventsContext);
  const conversions = useConversions();
  const { pathname } = useLocation();
  const [ended, setEnded] = useState<string | null>(null);
  const onNewModule = useRef(false);
  onNewModule.current = pathname === "/modules/new";

  useEffect(
    () =>
      subscribe({
        conversion: (data) => {
          const event = data as ConversionEvent | null;
          if (event?.id && (event.status === "done" || event.status === "failed") && !onNewModule.current) setEnded(event.id);
        },
      }),
    [subscribe],
  );

  // Once the list knows how it ended (it is fetched again on the event).
  const conversion = conversions.find((c) => c.id === ended && c.status !== "running");
  useEffect(() => {
    if (!conversion) return;
    setEnded(null);
    if (onNewModule.current) return;
    const link = conversionLink(conversion);
    if (conversion.status === "done")
      toast.success(
        <p>
          {t(makesModule(conversion) ? "conversion.noticeDone" : "conversion.noticeMapDone", { title: conversion.title })}{" "}
          {link && (
            <Link
              to={link}
              onClick={() => {
                markSeen(conversion.id);
                toast.dismiss(conversion.id);
              }}
            >
              {t(LINK_LABELS[conversion.kind])}
            </Link>
          )}
        </p>,
        { id: conversion.id, duration: 20_000 },
      );
    else
      toast.error(t("conversion.noticeFailed", { title: conversion.title, error: conversion.error ?? "" }), {
        id: conversion.id,
        duration: Infinity,
      });
  }, [conversion, t]);
  return null;
}
