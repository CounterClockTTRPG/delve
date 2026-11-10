import { Navigate, Route, Routes, useParams } from "react-router-dom";
import { ownerOf } from "./editorApi";
import ReviewPage from "./ReviewPage";
import WorldMapEditor from "./WorldMapEditor";

/**
 * The world-map screens, `/world-maps/:owner/:ownerId/:name/*`, loaded lazily so that Leaflet and Geoman stay out of
 * the main bundle: `""` is the editor, `review` the review of a map read from a picture. `owner` is `module`, `campaign` or `setting`; anything else goes back to the campaigns.
 */
export default function WorldMapRoutes() {
  const { owner: kind, ownerId, name } = useParams();
  const owner = ownerOf(kind, ownerId);
  if (!owner || !name) return <Navigate to="/campaigns" replace />;
  return (
    <Routes>
      <Route index element={<WorldMapEditor key={`${kind}/${ownerId}/${name}`} owner={owner} name={name} />} />
      <Route path="review" element={<ReviewPage key={`${kind}/${ownerId}/${name}`} owner={owner} name={name} />} />
    </Routes>
  );
}
