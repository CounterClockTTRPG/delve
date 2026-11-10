// The help topics in Dutch (DEL-284): a chunk of their own, fetched when a reader speaks it.
export default import.meta.glob("../topics/nl/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;
