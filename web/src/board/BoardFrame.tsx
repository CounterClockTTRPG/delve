import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, Outlet, useSearchParams } from "react-router-dom";
import "@fontsource/im-fell-english/400.css";
import { getMe, type Me } from "../account/api";
import { EventsContext } from "../api";
import { DialogsProvider } from "../components/dialogs";
import { I18nProvider, isLanguage, useT } from "../i18n";
import { boardKeys } from "./api";
import "./board.css";

// The message board's frame (DEL-297), around /board, /board/:zoneId and /board/:zoneId/:topicId: outside the app as
// the help is, so a visitor who isn't logged in reads the zones open to everybody. It knows who is reading (an account
// or the owner, or a visitor), speaks `?lang=` when it names a language, else the account's, else the browser's, and,
// for who is signed in, hears the board's events and reads again what they say changed.

/** Who reads the board: `signedIn` for an account or the owner, who may write; a visitor (or a seat) may not. */
interface Reader {
  signedIn: boolean;
}

const ReaderContext = createContext<Reader>({ signedIn: false });

export const useReader = () => useContext(ReaderContext);

/** Signed in as the board counts it: an account, or the owner by token. A seat's token reads as a visitor's. */
export const signedIn = (me: Me | undefined): boolean => Boolean(me?.account || me?.principal?.id === "owner");

/** The frame as the router mounts it, with the pages in its outlet. */
export default function BoardFrame() {
  return (
    <BoardFrameAround>
      <Outlet />
    </BoardFrameAround>
  );
}

/** The frame around `children`: its own query client, the language, Delve's dialogs, the reader and the events. */
export function BoardFrameAround({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }));
  return (
    <QueryClientProvider client={client}>
      <Speaking>{children}</Speaking>
    </QueryClientProvider>
  );
}

function Speaking({ children }: { children: ReactNode }) {
  const [search] = useSearchParams();
  // A 401 here says only that nobody is logged in: a visitor.
  const me = useQuery({ queryKey: ["board-reader"], queryFn: () => getMe(), retry: false, staleTime: Infinity });
  const asked = search.get("lang");
  const browser = (typeof navigator !== "undefined" ? navigator.language : "en").slice(0, 2).toLowerCase();
  const language = isLanguage(asked) ? asked : (me.data?.account?.language ?? browser);
  if (me.isPending) return null;
  return (
    <I18nProvider language={language}>
      <DialogsProvider>
        <ReaderContext.Provider value={{ signedIn: signedIn(me.data) }}>
          <BoardEvents />
          <Frame>{children}</Frame>
        </ReaderContext.Provider>
      </DialogsProvider>
    </I18nProvider>
  );
}

/** The board's events, for who is signed in (the stream is 401 for a visitor): each says a zone, or a topic in it,
 * changed, and the board's queries are read again, the zone or topic on screen with them (`boardKeys.all` is their
 * common start). */
function BoardEvents() {
  const client = useQueryClient();
  const subscribe = useContext(EventsContext);
  const { signedIn: listening } = useReader();
  useEffect(() => {
    if (!listening) return;
    return subscribe({ board: () => void client.invalidateQueries({ queryKey: boardKeys.all }) });
  }, [client, subscribe, listening]);
  return null;
}

function Frame({ children }: { children: ReactNode }) {
  const t = useT();
  const { signedIn: inside } = useReader();
  return (
    <div className="board">
      <header className="board-head">
        <a className="board-home" href={inside ? "/home" : "/"}>
          <img src="/favicon.svg" alt="" width={22} height={22} />
          {t("app.name")}
        </a>
        <Link className="board-title-link" to="/board">
          {t("board.title")}
        </Link>
        {inside ? (
          <a className="board-out" href="/home">
            {t("board.backToDelve")}
          </a>
        ) : (
          <a className="board-out" href="/login">
            {t("landing.logIn")}
          </a>
        )}
      </header>
      {children}
      <footer className="board-foot">
        <a href="/">{t("app.name")}</a>
        <a href="/help">{t("landing.help")}</a>
        <a href="/privacy">{t("legal.privacy")}</a>
        <a href="/terms">{t("legal.terms")}</a>
      </footer>
    </div>
  );
}
