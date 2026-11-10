import { describe, expect, it } from "vitest";
import { quoteOf, renderPost } from "./markdown";

describe("renderPost", () => {
  it("renders the formatting a post may carry", () => {
    const html = renderPost("**b** *i* `c`\n\n# H\n\n- a\n\n> q");
    expect(html).toContain("<strong>b</strong>");
    expect(html).toContain("<em>i</em>");
    expect(html).toContain("<code>c</code>");
    expect(html).toContain("<h1>H</h1>");
    expect(html).toContain("<li>a</li>");
    expect(html).toContain("<blockquote>");
  });
  it("leaves raw HTML as text", () => {
    expect(renderPost("<script>alert(1)</script><img src=x onerror=alert(1)>")).not.toMatch(/<script|<img/);
  });
  it("links only to http(s) and mailto, safely", () => {
    expect(renderPost("[x](javascript:alert(1))")).not.toContain('href="javascript');
    expect(renderPost("[x](https://delve.party)")).toContain('rel="noopener noreferrer nofollow"');
    expect(renderPost("[x](https://delve.party)")).toContain('target="_blank"');
    expect(renderPost("[x](mailto:a@b.c)")).toContain('href="mailto:a@b.c"');
  });
  it("links to Delve's own pages in the same tab", () => {
    const html = renderPost("[Help](/help/find-a-table)");
    expect(html).toContain('href="/help/find-a-table"');
    expect(html).not.toContain("target=");
    expect(renderPost("[x](//elsewhere.example/a)")).not.toContain("href=");
    expect(renderPost("[x](/\\elsewhere.example/a)")).not.toMatch(/href="\/\\/);
  });
  it("loads no image from Markdown", () => {
    expect(renderPost("![t](https://elsewhere/t.png)")).not.toContain("<img");
  });
});

describe("quoteOf", () => {
  it("quotes every line under who wrote it", () => {
    expect(quoteOf("Ana", "one\ntwo")).toBe("> **Ana wrote:**\n> one\n> two\n\n");
  });
});
