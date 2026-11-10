/**
 * System alerts: messages from Delve itself, not from the screen's content (docs/style-guide.md, "Alerts"). A
 * component raises one while its condition holds (`useSystemAlert`), and the stack at the top of the page shows it,
 * the same on every screen. Each has an id, a tone (info, warning or error), its words and, optionally, one action.
 * A dismissible alert closes with ×, and this browser remembers it by its id, so it doesn't come back on the next
 * page; one that must be acted on (the event stream lost) is not dismissible.
 */
import { AlertTriangle, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { safeStorage } from "../desktop/storage";
import { useT } from "../i18n";

export type AlertTone = "info" | "warning" | "error";

export interface SystemAlert {
  /** Names the alert: raising it again replaces it, and a dismissal is kept under it. */
  id: string;
  tone: AlertTone;
  text: string;
  /** Default true. */
  dismissible?: boolean;
  action?: { label: string; onClick: () => void };
}

const DISMISSED = "delve.alerts.dismissed";

function readDismissed(): Set<string> {
  try {
    const stored: unknown = JSON.parse(safeStorage.getItem(DISMISSED) ?? "[]");
    return new Set(Array.isArray(stored) ? stored.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

interface Alerts {
  shown: SystemAlert[];
  /** How many stacks are placed inside a page's layout (`<SystemAlerts />`); the page-wide one stands back for them. */
  placed: number;
  place: () => () => void;
  raise: (alert: SystemAlert) => void;
  drop: (id: string) => void;
  dismiss: (id: string) => void;
}

const AlertsContext = createContext<Alerts | null>(null);

export function AlertsProvider({ children }: { children: ReactNode }) {
  const [raised, setRaised] = useState<SystemAlert[]>([]);
  const [dismissed, setDismissed] = useState(readDismissed);
  const [placed, setPlaced] = useState(0);
  const place = useCallback(() => {
    setPlaced((n) => n + 1);
    return () => setPlaced((n) => n - 1);
  }, []);
  const raise = useCallback(
    (alert: SystemAlert) => setRaised((all) => [...all.filter((a) => a.id !== alert.id), alert]),
    [],
  );
  const drop = useCallback((id: string) => setRaised((all) => all.filter((a) => a.id !== id)), []);
  const dismiss = useCallback((id: string) => {
    setDismissed((was) => {
      const next = new Set(was).add(id);
      safeStorage.setItem(DISMISSED, JSON.stringify([...next]));
      return next;
    });
  }, []);
  const shown = useMemo(
    () => raised.filter((a) => a.dismissible === false || !dismissed.has(a.id)),
    [raised, dismissed],
  );
  const value = useMemo(() => ({ shown, placed, place, raise, drop, dismiss }), [shown, placed, place, raise, drop, dismiss]);
  return <AlertsContext.Provider value={value}>{children}</AlertsContext.Provider>;
}

/** Raise `alert` while it is given and this component is mounted; null (or unmounting) takes it down. Outside an
 * `AlertsProvider` (a screen rendered alone in a test) it does nothing. */
export function useSystemAlert(alert: SystemAlert | null) {
  const alerts = useContext(AlertsContext);
  // The action's handler may be a new function on every render: the alert calls the latest.
  const onAction = useRef(alert?.action?.onClick);
  onAction.current = alert?.action?.onClick;
  const { id, tone, text, dismissible } = alert ?? {};
  const label = alert?.action?.label;
  useEffect(() => {
    if (!alerts || !id || !tone || text === undefined) return;
    alerts.raise({
      id,
      tone,
      text,
      dismissible,
      action: label ? { label, onClick: () => onAction.current?.() } : undefined,
    });
    return () => alerts.drop(id);
    // `alerts` changes with what is shown; its raise and drop never change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts?.raise, alerts?.drop, id, tone, text, dismissible, label]);
}

const ICONS = { info: Info, warning: AlertTriangle, error: XCircle } as const;

/** The stack of raised alerts, newest last. A page's layout places it at the top of its content (the shell, beside the
 * side bar); the page-wide one (`pageWide`, at the top of every page) shows only where no layout placed one, as on the
 * map editor. */
export function SystemAlerts({ pageWide = false }: { pageWide?: boolean }) {
  const t = useT();
  const alerts = useContext(AlertsContext);
  const place = alerts?.place;
  useEffect(() => (pageWide || !place ? undefined : place()), [pageWide, place]);
  if (!alerts || alerts.shown.length === 0 || (pageWide && alerts.placed > 0)) return null;
  return (
    <section className="system-alerts" aria-label={t("alerts.label")}>
      {alerts.shown.map((alert) => {
        const Icon = ICONS[alert.tone];
        return (
          <div
            key={alert.id}
            className={`system-alert ${alert.tone}`}
            role={alert.tone === "info" ? "status" : "alert"}
            data-testid={alert.id}
          >
            <Icon className="system-alert-icon" size={18} aria-hidden="true" />
            <span className="system-alert-text">{alert.text}</span>
            {alert.action && (
              <button type="button" onClick={alert.action.onClick}>
                {alert.action.label}
              </button>
            )}
            {alert.dismissible !== false && (
              <button
                type="button"
                className="icon system-alert-dismiss"
                aria-label={t("alerts.dismiss")}
                title={t("alerts.dismiss")}
                onClick={() => alerts.dismiss(alert.id)}
              >
                <X size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        );
      })}
    </section>
  );
}
