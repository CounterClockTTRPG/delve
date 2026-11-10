// Posts are Markdown by people, shown to people (DEL-297): no raw HTML, no images (a post's picture is its own
// attachment), links only to http(s), mailto and Delve's own pages ("/help/…"); a link off Delve opens in a new tab
// without handing over the page.
import MarkdownIt from "markdown-it";

const SAFE_LINK = /^(https?:|mailto:|\/(?![/\\]))/i;
const OWN_PAGE = /^\/(?![/\\])/;

const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
md.disable("image");
md.validateLink = (url) => SAFE_LINK.test(url.trim());

const openLink = md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  if (OWN_PAGE.test(tokens[idx].attrGet("href") ?? "")) return openLink(tokens, idx, options, env, self);
  tokens[idx].attrSet("target", "_blank");
  tokens[idx].attrSet("rel", "noopener noreferrer nofollow");
  return openLink(tokens, idx, options, env, self);
};

/** A post's text as safe HTML. */
export const renderPost = (text: string): string => md.render(text);

/** The text quoted under who wrote it, ready to start a reply with. */
export const quoteOf = (author: string, text: string): string =>
  `> **${author} wrote:**\n${text.split("\n").map((line) => `> ${line}`).join("\n")}\n\n`;
