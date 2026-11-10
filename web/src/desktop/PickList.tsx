import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef, type ReactNode } from "react";

/** From this many rows a list draws only the rows in view (Barrowmaze has 384 encounters). */
export const VIRTUAL_FROM = 100;

/**
 * A list of rows to pick from. A short one is a plain list; a long one scrolls in its own box and keeps only the rows in
 * view, and the current row is scrolled into view when the list opens.
 */
export default function PickList<T>({
  items,
  keyOf,
  render,
  current,
  rowHeight = 36,
}: {
  items: T[];
  keyOf: (item: T) => string;
  render: (item: T) => ReactNode;
  /** The index of the row that is open, if any. */
  current?: number;
  /** A row's height in pixels, before it is measured. */
  rowHeight?: number;
}) {
  if (items.length < VIRTUAL_FROM)
    return (
      <ul>
        {items.map((item) => (
          <li key={keyOf(item)}>{render(item)}</li>
        ))}
      </ul>
    );
  return <VirtualRows items={items} keyOf={keyOf} render={render} current={current} rowHeight={rowHeight} />;
}

function VirtualRows<T>({
  items,
  keyOf,
  render,
  current,
  rowHeight,
}: {
  items: T[];
  keyOf: (item: T) => string;
  render: (item: T) => ReactNode;
  current?: number;
  rowHeight: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const rows = useVirtualizer({
    count: items.length,
    getScrollElement: () => box.current,
    estimateSize: () => rowHeight,
    getItemKey: (index) => keyOf(items[index]),
    overscan: 8,
    // Before the box is measured (and in tests, where nothing is) it counts as one screen tall.
    initialRect: { width: 0, height: 600 },
  });
  useEffect(() => {
    if (current !== undefined && current >= 0) rows.scrollToIndex(current, { align: "auto" });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div ref={box} className="pick-list-scroll" data-testid="pick-list-scroll">
      <ul style={{ height: rows.getTotalSize(), position: "relative" }}>
        {rows.getVirtualItems().map((row) => (
          <li
            key={row.key}
            data-index={row.index}
            ref={rows.measureElement}
            style={{ position: "absolute", top: 0, left: 0, right: 0, transform: `translateY(${row.start}px)` }}
          >
            {render(items[row.index])}
          </li>
        ))}
      </ul>
    </div>
  );
}
