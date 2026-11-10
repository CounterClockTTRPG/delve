import { Children, type ReactNode } from "react";
import Split from "./Split";
import { useWide } from "./useMedia";

/** A list beside the editor of its open item: a split from 900 px, the grid of `className` (styles.css) otherwise. */
export default function ListAndEditor({ id, className, children }: { id: string; className: string; children: ReactNode }) {
  const wide = useWide();
  const [list, editor] = Children.toArray(children);
  if (!wide)
    return (
      <div className={className}>
        {list}
        {editor}
      </div>
    );
  return (
    <Split
      id={id}
      className={`${className} list-and-editor`}
      overflow="visible"
      start={{ size: 22, min: 180, children: list, className: "list-pane" }}
      end={{ size: 78, min: 360, children: editor ?? null, className: "editor-pane" }}
    />
  );
}
