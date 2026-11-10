import type { MessageKey } from "../i18n";

// Delve's keyboard shortcuts, in the order the help lists them. `keys` is react-hotkeys-hook's form (">" between the
// keys of a sequence); `shown` is how the help prints it. The owner's alone are `owner`: a seat has nowhere to go.

export type Shortcut = { keys: string; shown: string; label: MessageKey; owner?: true; to?: string };

export const GO_TO: Shortcut[] = [
  { keys: "g>p", shown: "g p", label: "area.play", owner: true, to: "/play" },
  { keys: "g>c", shown: "g c", label: "area.campaigns", owner: true, to: "/campaigns" },
  { keys: "g>m", shown: "g m", label: "area.modules", owner: true, to: "/modules" },
  { keys: "g>a", shown: "g a", label: "area.maps", owner: true, to: "/maps" },
  { keys: "g>h", shown: "g h", label: "area.houseRules", owner: true, to: "/house-rules" },
  { keys: "g>b", shown: "g b", label: "rulesets.title", owner: true, to: "/rulesets" },
  { keys: "g>s", shown: "g s", label: "area.settings", owner: true, to: "/settings" },
  { keys: "g>r", shown: "g r", label: "area.preferences", owner: true, to: "/preferences" },
];

export const SHORTCUTS: Shortcut[] = [
  { keys: "mod+k", shown: "Ctrl K", label: "shortcuts.palette", owner: true },
  { keys: "/", shown: "/", label: "shortcuts.composer" },
  { keys: "", shown: "Enter", label: "shortcuts.act" },
  { keys: "", shown: "Ctrl Enter", label: "shortcuts.ask" },
  { keys: "", shown: "Shift Enter", label: "shortcuts.newLine" },
  { keys: "", shown: "Esc", label: "shortcuts.close" },
  { keys: "?", shown: "?", label: "shortcuts.help" },
];
