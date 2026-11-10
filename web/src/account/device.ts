// The browsers an account is logged in on, named from their User-Agent (players and tavern Task E4): "Firefox on
// Linux", "Safari on iPhone", or "A browser" for one it doesn't know.
import { translate, type Translate } from "../i18n";

const english: Translate = (key, vars) => translate("en", key, vars);

// The first that matches wins: Edge and Opera say Chrome too, and Chrome says Safari.
const BROWSERS: [RegExp, string][] = [
  [/\bEdg(e|A|iOS)?\//, "Edge"],
  [/\bOPR\//, "Opera"],
  [/\b(Firefox|FxiOS)\//, "Firefox"],
  [/\b(Chrome|CriOS|Chromium)\//, "Chrome"],
  [/\bSafari\//, "Safari"],
];

const SYSTEMS: [RegExp, string][] = [
  [/\biPhone\b/, "iPhone"],
  [/\biPad\b/, "iPad"],
  [/\bAndroid\b/, "Android"],
  [/\bWindows\b/, "Windows"],
  [/\bMac OS X\b|\bMacintosh\b/, "macOS"],
  [/\bCrOS\b/, "ChromeOS"],
  [/\bLinux\b/, "Linux"],
];

function first(table: [RegExp, string][], text: string): string | null {
  return table.find(([pattern]) => pattern.test(text))?.[1] ?? null;
}

export function deviceLabel(userAgent: string, t: Translate = english): string {
  const browser = first(BROWSERS, userAgent);
  const system = first(SYSTEMS, userAgent);
  if (!browser) return t("device.unknown");
  return system ? t("device.on", { browser, system }) : browser;
}
