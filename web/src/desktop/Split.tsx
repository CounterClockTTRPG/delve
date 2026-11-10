import type { ReactNode } from "react";
import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";
import { useT } from "../i18n";
import { safeStorage } from "./storage";

export type Pane = {
  children: ReactNode;
  /** Its share of the width when nothing is remembered, in percent. */
  size: number;
  /** The narrowest it may be dragged, in pixels. */
  min: number;
  className?: string;
};

/**
 * Two panes side by side with a divider between them: dragged with the mouse, moved with the arrow keys when it has
 * the focus, and back to the first layout on a double-click. Each browser remembers each split's widths
 * (`delve.split.<id>` in local storage). Only for wide screens: under 900 px the screens stack instead.
 */
export default function Split({
  id,
  start,
  end,
  className,
  overflow,
}: {
  id: string;
  start: Pane;
  end: Pane;
  className?: string;
  /** "visible" lets an editor's menus reach past its pane; by default each pane clips what it holds. */
  overflow?: "visible";
}) {
  const t = useT();
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: `delve.split.${id}`,
    storage: safeStorage,
    onlySaveAfterUserInteractions: true,
  });
  return (
    <Group
      id={`split-${id}`}
      orientation="horizontal"
      className={className ? `split ${className}` : "split"}
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
    >
      <Panel
        id="start"
        className={start.className ? `split-pane ${start.className}` : "split-pane"}
        style={overflow ? { overflow } : undefined}
        defaultSize={`${start.size}`}
        minSize={start.min}
      >
        {start.children}
      </Panel>
      <Separator className="split-handle" aria-label={t("split.handle")} title={t("split.handleHint")} />
      <Panel
        id="end"
        className={end.className ? `split-pane ${end.className}` : "split-pane"}
        style={overflow ? { overflow } : undefined}
        defaultSize={`${end.size}`}
        minSize={end.min}
      >
        {end.children}
      </Panel>
    </Group>
  );
}
