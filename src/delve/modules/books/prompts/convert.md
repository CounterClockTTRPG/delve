You are converting part of a role-playing adventure module from a PDF into Markdown. The text between `<source>`
and `</source>` was read from {{pages}} of “{{title}}”, in reading order. Re-express it faithfully: every word
of the module stays, in its own words and in its own order.

Write it as Markdown:

- A chapter of the book is a `#` heading, with the chapter's title as printed.
- A keyed area is a `## <key>. <name>` heading, with the key as printed: `## 12. The Well Room`, `## C3. Guard Post`,
  `## W101. Dwarven Guard Post`. Other headings inside a chapter are `##` to `####` headings, as the book nests them.
- Boxed text, or text the book says to read aloud to the players, is a blockquote (`> `) straight after its heading.
- A table is a Markdown table, with every row and column.
- Keep the book's `**bold**` and `*italic*` as they are.
- NPC and monster stat lines stay as they are printed (`AC 5; MV 9; HD 2; hp 11; THAC0 19; #AT 1; Dmg 1d8`).
- Copy every number, die roll and table row exactly as the book has it, even when it looks wrong or a sequence has
  gaps; never renumber, never fill in a row.
- When a chapter is meant for the players (a players' introduction or handout, as the book says), put the line
  `<!-- players -->` straight after its `#` heading.

Keep out what isn't the module's text: running headers and footers, page numbers, and words broken across lines
(join them). Never summarise, shorten, explain or comment. Don't add a title, a preamble or a closing note, and
don't put the answer in a code block. If these pages begin in the middle of a section, continue it without a new
heading.

{{context}}<source>
{{text}}
</source>

Answer with the Markdown only. Only when these pages leave you unsure of something the DM needs to know (a key
that is unreadable, a table that doesn't add up, two pages that contradict each other), end the answer with at most 5
questions, each with what you assumed, in one fenced `questions` block:

```questions
[{"text": "Room 12's door is unreadable: is it locked?", "default": "Assumed it is locked, as room 11's is."}]
```

A value the text layer lost (a field with nothing after it, such as "HD ;", a stray `;` or `,`, or an empty table
cell) was printed on the page: keep the line as it is given, and a question about it has the default "Unknown: read
it from the page", never "as printed".
