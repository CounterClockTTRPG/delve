// A chapter's Markdown as HTML, through the module texts' own reading (`fromMarkdown` and the editor's schema), as
// the module's print view renders them. The schema builds the DOM, so markup in the text stays text.
import { getSchema } from "@tiptap/core";
import { DOMSerializer, Node as PMNode } from "@tiptap/pm/model";
import { fromMarkdown, moduleTextExtensions } from "../module/MarkdownRoundTrip";

let schema: ReturnType<typeof getSchema> | null = null;

export function chapterHtml(markdown: string): string {
  schema ??= getSchema(moduleTextExtensions());
  const doc = PMNode.fromJSON(schema, fromMarkdown(markdown));
  const holder = document.createElement("div");
  holder.append(DOMSerializer.fromSchema(schema).serializeFragment(doc.content));
  return holder.innerHTML;
}
