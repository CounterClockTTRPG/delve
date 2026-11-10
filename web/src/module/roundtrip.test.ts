import { Editor, type JSONContent } from "@tiptap/core";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fromMarkdown, headingAnchor, headingKey, moduleTextExtensions, toMarkdown } from "./MarkdownRoundTrip";

// Review Focus 1: opening a text and saving it without edits gives the same Markdown, byte for byte.

// Tests run in web/.
const here = join(process.cwd(), "src/module");
const cryptText = join(here, "../../../tests/fixtures/samples/scenarios/crypt-of-saint-vellis/text");

function markdownFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return markdownFiles(path);
    return name.endsWith(".md") ? [path] : [];
  });
}

const TEXTS: [string, string][] = [
  ...markdownFiles(cryptText).map((path): [string, string] => [path.slice(cryptText.length + 1), readFileSync(path, "utf8")]),
  ["fixtures/everything.md", readFileSync(join(here, "fixtures/everything.md"), "utf8")],
];

/** The document as the editor holds it: through the schema and back. */
function throughEditor(doc: JSONContent): JSONContent {
  const editor = new Editor({ extensions: moduleTextExtensions(), content: doc });
  const json = editor.getJSON();
  editor.destroy();
  return json;
}

/** The document without what the parser remembers of the source, so only the serialiser writes. */
function withoutSource(node: JSONContent): JSONContent {
  const attrs = node.attrs ? { ...node.attrs, source: null } : undefined;
  return { ...node, ...(attrs ? { attrs } : {}), ...(node.content ? { content: node.content.map(withoutSource) } : {}) };
}

function find(node: JSONContent, type: string): JSONContent[] {
  const own = node.type === type ? [node] : [];
  return [...own, ...(node.content ?? []).flatMap((child) => find(child, type))];
}

describe("the Markdown round-trip", () => {
  it("finds the crypt's texts", () => {
    expect(TEXTS.map(([name]) => name).sort()).toEqual(["fixtures/everything.md", "intro.md", "keyed/crypt.md"]);
  });

  it.each(TEXTS)("gives %s back byte for byte", (_name, md) => {
    expect(toMarkdown(fromMarkdown(md))).toBe(md);
  });

  it.each(TEXTS)("gives %s back byte for byte through the editor", (_name, md) => {
    expect(toMarkdown(throughEditor(fromMarkdown(md)))).toBe(md);
  });

  it.each(TEXTS)("writes %s in its own format, without the source it remembers", (_name, md) => {
    expect(toMarkdown(throughEditor(withoutSource(fromMarkdown(md))))).toBe(md);
  });

  it("keeps the front matter out of the document and writes it back", () => {
    const md = readFileSync(join(cryptText, "keyed/crypt.md"), "utf8");
    const doc = fromMarkdown(md);
    expect(doc.attrs?.frontMatter).toBe("---\ntitle: Crypt — keyed encounters\n---\n\n");
    expect(JSON.stringify(doc.content)).not.toContain("title: Crypt");
    expect(doc.content?.[0]).toMatchObject({ type: "heading", attrs: { level: 2, anchor: "c1" } });
  });

  it("reads every construct of the fixture into its own node", () => {
    const doc = fromMarkdown(TEXTS.find(([name]) => name === "fixtures/everything.md")![1]);
    const anchors = find(doc, "heading").map((h) => h.attrs?.anchor);
    expect(anchors).toEqual([null, "approach", "a1", "a1-treasure", null, null]);
    expect(find(doc, "entityRef").map((r) => `${r.attrs?.kind}:${r.attrs?.id}`)).toEqual([
      "npc:brother-ansel",
      "faction:grey-lantern",
      "npc:brother-hugh",
      "quest:the-drowned-abbot",
    ]);
    expect(find(doc, "image")[0].attrs).toMatchObject({ src: "asset:courtyard", alt: "The flooded courtyard at dusk" });
    expect(find(doc, "blockquote")).toHaveLength(2);
    expect(find(doc, "hardBreak")).toHaveLength(1);
    expect(find(doc, "table")).toHaveLength(1);
    expect(find(doc, "orderedList")).toHaveLength(1);
    expect(find(doc, "bulletList")).toHaveLength(2);
    expect(find(doc, "rawBlock")).toHaveLength(0);
  });

  it("keys a bare room number, and keeps the digit guard", () => {
    expect(headingKey(2, "31.")).toBe("31");
    expect(headingKey(2, "C3:")).toBe("C3");
    expect(headingKey(2, "31. The Well")).toBe("31");
    for (const text of ["Treasure:", "Epilogue.", "Note: also not keyed", "31.5 gp"]) expect(headingKey(2, text)).toBeNull();
    expect(headingAnchor(2, "31.", null)).toBe("31");
  });

  it("keeps a text written in another style as it was, until a block of it is edited", () => {
    const md = "Setext title\n============\n\n* one\n* two\n\n__bold__ and _it_\n## Next\nText &amp; more\n";
    expect(toMarkdown(throughEditor(fromMarkdown(md)))).toBe(md);

    const doc = throughEditor(fromMarkdown(md));
    // Edit the list: only the list is written in the editor's own style.
    const list = doc.content![1];
    list.content![1].content![0].content![0].text = "three";
    expect(toMarkdown(doc)).toBe("Setext title\n============\n\n* one\n* three\n\n__bold__ and _it_\n## Next\nText &amp; more\n");
    list.content!.push({ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "four" }] }] });
    expect(toMarkdown(doc)).toContain("* one\n* three\n* four\n\n__bold__");
  });

  it("escapes what would otherwise be Markdown", () => {
    const tricky = "# not a heading *nor* [a link] or `code`, 2_x_ <b> & &amp; ~gone~ \\ ok";
    const doc: JSONContent = {
      type: "doc",
      content: [
        { type: "paragraph", content: [{ type: "text", text: tricky }] },
        { type: "paragraph", content: [{ type: "text", text: "1. not a list" }] },
        { type: "paragraph", content: [{ type: "text", text: "- nor this" }] },
        { type: "paragraph", content: [{ type: "text", text: "> nor a quote" }] },
      ],
    };
    const md = toMarkdown(doc);
    const back = fromMarkdown(md);
    expect(back.content?.map((block) => block.type)).toEqual(["paragraph", "paragraph", "paragraph", "paragraph"]);
    expect(back.content?.map((block) => block.content?.map((n) => n.text).join(""))).toEqual([
      tricky,
      "1. not a list",
      "- nor this",
      "> nor a quote",
    ]);
  });

  it("writes marks around the words, not their spaces", () => {
    const doc: JSONContent = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "a " },
            { type: "text", text: "bold ", marks: [{ type: "bold" }] },
            { type: "text", text: "and both", marks: [{ type: "bold" }, { type: "italic" }] },
            { type: "text", text: " end" },
          ],
        },
      ],
    };
    expect(toMarkdown(doc)).toBe("a **bold *and both*** end\n");
  });

  it("drops empty paragraphs and starts a new text with nothing", () => {
    expect(toMarkdown(fromMarkdown(""))).toBe("");
    const doc: JSONContent = { type: "doc", content: [{ type: "paragraph" }, { type: "paragraph", content: [{ type: "text", text: "Hello" }] }, { type: "paragraph" }] };
    expect(toMarkdown(doc)).toBe("Hello\n");
  });

  it("keeps apart two lists that follow each other", () => {
    const item = (text: string) => ({ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text }] }] });
    const doc: JSONContent = {
      type: "doc",
      content: [
        { type: "bulletList", content: [item("a")] },
        { type: "bulletList", content: [item("b")] },
      ],
    };
    expect(fromMarkdown(toMarkdown(doc)).content?.map((block) => block.type)).toEqual(["bulletList", "bulletList"]);
  });

  it("keeps what it can't edit as it is", () => {
    const md = "<div class=\"box\">\nHand-written HTML\n</div>\n\n- [ ] a task\n\nAfter.\n";
    const doc = fromMarkdown(md);
    expect(doc.content?.map((block) => block.type)).toEqual(["rawBlock", "rawBlock", "paragraph"]);
    expect(toMarkdown(throughEditor(doc))).toBe(md);
  });

  it("keeps a heading's anchor with its text when the heading is split", () => {
    const editor = new Editor({ extensions: moduleTextExtensions(), content: fromMarkdown("## Entry Hall {#hall}\n") });
    // Enter at the start of the heading: an empty heading above, the anchor stays with "Entry Hall".
    editor.chain().setTextSelection(1).splitBlock().run();
    expect(toMarkdown(editor.getJSON())).toBe("## Entry Hall {#hall}\n");
    // Enter in the middle ("Entry| Hall", after the empty heading): the anchor isn't written twice.
    editor.chain().setTextSelection(2 + 1 + "Entry".length).splitBlock().run();
    expect(toMarkdown(editor.getJSON())).toBe("## Entry {#hall}\n\n## Hall\n");
    editor.destroy();
  });

  it("writes a keyed heading as it is typed", () => {
    const heading = (text: string) => ({ type: "heading", attrs: { level: 2 }, content: [{ type: "text", text }] });
    expect(toMarkdown({ type: "doc", content: [heading("12. The Crypt"), heading("Hash #")] })).toBe("## 12. The Crypt\n\n## Hash \\#\n");
  });

  it("gives a heading's anchor: explicit, or the key's slug", () => {
    expect(headingAnchor(2, "C1. Entry Hall", "c1")).toBe("c1");
    expect(headingAnchor(2, "W101. Dwarven Guard Post", null)).toBe("w101");
    expect(headingAnchor(2, "Note: about this", null)).toBeNull();
    expect(headingAnchor(1, "WGR1: Greyhawk Ruins", null)).toBeNull();
    expect(headingAnchor(3, "Approach", null)).toBeNull();
  });
});
