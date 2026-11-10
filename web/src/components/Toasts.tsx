import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { CSSProperties } from "react";
import { Toaster } from "sonner";
import { useWide } from "../desktop/useMedia";
import { useT } from "../i18n";

// sonner's own colours, set from Delve's tokens so the notifications follow the look and its dark set.
const TOKENS = {
  "--normal-bg": "var(--surface)",
  "--normal-text": "var(--ink)",
  "--normal-border": "var(--rule)",
  "--error-bg": "var(--error-bg)",
  "--error-text": "var(--error)",
  "--error-border": "var(--error)",
  // The close button inside the top right corner, instead of over the top left one.
  "--toast-close-button-start": "unset",
  "--toast-close-button-end": "0",
  "--toast-close-button-transform": "translate(35%, -35%)",
} as CSSProperties;

const ICONS = {
  success: <CheckCircle2 size={18} aria-hidden="true" />,
  error: <AlertTriangle size={18} aria-hidden="true" />,
  info: <Info size={18} aria-hidden="true" />,
};

/**
 * Where notifications show: the bottom right corner, a few at a time, each closable; above the tab bar under 900 px.
 * Each is a card in the look's colours (styles.css `.toast`): an icon and a coloured edge by its kind, done or failed.
 */
export default function Toasts() {
  const t = useT();
  const bottom = useWide() ? "1rem" : "calc(var(--tabbar-height) + 1rem)";
  return (
    <Toaster
      position="bottom-right"
      visibleToasts={4}
      closeButton
      offset={{ bottom, right: "1rem" }}
      mobileOffset={{ bottom, right: "1rem", left: "1rem" }}
      style={TOKENS}
      icons={ICONS}
      toastOptions={{ className: "toast", closeButtonAriaLabel: t("toast.close") }}
      containerAriaLabel={t("toast.region")}
    />
  );
}
