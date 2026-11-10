import ProvenanceNotice from "./ProvenanceNotice";

/**
 * The notice of a drafted map (`ProvenanceNotice`): a sketch's invented layout, with the book's map and the offer to
 * draw from it, or the book's page or the description a draft was drawn from.
 */
export default function SketchNotice(props: {
  moduleId: string;
  source: string;
  mapName?: string;
  className?: string;
}) {
  return <ProvenanceNotice {...props} />;
}
