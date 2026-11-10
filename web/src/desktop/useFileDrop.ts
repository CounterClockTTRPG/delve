import { useEffect, useRef, useState } from "react";

/** Whether a drag carries files from outside the page (not a dragged map token or text). */
function carriesFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

/**
 * A file dropped anywhere on the window, while `enabled`: `onFile` gets the first one. Answers whether files are being
 * dragged over the window, for the screen to say what a drop does.
 */
export function useFileDrop(onFile: (file: File) => void, enabled = true): boolean {
  const [dragging, setDragging] = useState(false);
  const take = useRef(onFile);
  take.current = onFile;
  useEffect(() => {
    if (!enabled) {
      setDragging(false);
      return;
    }
    // Enter and leave fire for every element crossed; the count is back to 0 when the drag leaves the window.
    let depth = 0;
    const enter = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      depth++;
      setDragging(true);
    };
    const leave = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const over = (e: DragEvent) => {
      if (carriesFiles(e)) e.preventDefault();
    };
    const drop = (e: DragEvent) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      depth = 0;
      setDragging(false);
      const file = e.dataTransfer?.files?.[0];
      if (file) take.current(file);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, [enabled]);
  return dragging;
}
