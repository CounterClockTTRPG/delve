// The help topics in Latvian (DEL-284): a chunk of their own, fetched when a reader speaks it.
export default import.meta.glob("../topics/lv/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;
