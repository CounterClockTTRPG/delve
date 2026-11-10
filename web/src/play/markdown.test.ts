import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

describe("renderMarkdown", () => {
  it("renders a table with its header, alignment row and inline Markdown", () => {
    const html = renderMarkdown("Rolled:\n\n| STR | DEX |\n|---|:---:|\n| 15 | **16** |\n| 6 | 11 |");
    expect(html).toBe(
      "<p>Rolled:</p>" +
        "<table><thead><tr><th>STR</th><th>DEX</th></tr></thead>" +
        "<tbody><tr><td>15</td><td><strong>16</strong></td></tr><tr><td>6</td><td>11</td></tr></tbody></table>",
    );
  });

  it("starts a table right after a paragraph line, and keeps escaped pipes in a cell", () => {
    const html = renderMarkdown("Scores\n| a | b |\n|---|---|\n| x \\| y | z |");
    expect(html).toBe(
      "<p>Scores</p><table><thead><tr><th>a</th><th>b</th></tr></thead><tbody><tr><td>x | y</td><td>z</td></tr></tbody></table>",
    );
  });

  it("leaves pipes without an alignment row as text", () => {
    expect(renderMarkdown("a | b\nc | d")).toBe("<p>a | b c | d</p>");
  });

  it("escapes a table's cells like everything else", () => {
    const html = renderMarkdown("| <b>x</b> |\n|---|\n| y |");
    expect(html).toContain("<th>&lt;b&gt;x&lt;/b&gt;</th>");
    expect(html).not.toContain("<b>");
  });

  it("still renders a quote", () => {
    expect(renderMarkdown("> The door is sealed.\n> It hums.")).toBe(
      '<blockquote class="read-aloud">The door is sealed.<br>It hums.</blockquote>',
    );
  });
});
