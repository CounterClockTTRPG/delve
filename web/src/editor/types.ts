// Shapes the editor exchanges with Delve's module, map and DSL routes
// (plan 1, task 6). Ported from dungml's lib/types.ts and lib/api.ts; the
// map shapes are module-scoped, and `kind` is `role`.

export type MapRole = "map" | "library";

export interface MapDetail {
  module_id: string;
  name: string;
  role: MapRole;
  is_default: boolean;
  updated_at: string;
  source: string;
}

export type Severity = "error" | "warning";

export interface Diagnostic {
  severity: Severity;
  message: string;
  line: number;
  column: number;
  end_line: number;
  end_column: number;
}

export interface RenderResponse {
  svg: string;
  diagnostics: Diagnostic[];
}

/** A 400 from a render or save: the source doesn't parse. */
export interface ParseErrorBody {
  error: string;
  line?: number;
  column?: number;
}

export interface NodeConnection {
  to: string; // neighbour node id, or "(exterior)"
  type: string;
  state: string;
  direction: "both" | "out" | "in";
}

export interface NodeConnectivity {
  id: string; // "room.hall" / "corridor.c1"
  kind: "room" | "corridor";
  name: string;
  connected: boolean;
  doors: number;
  connections: NodeConnection[];
}

export interface ConnectivityResponse {
  nodes: NodeConnectivity[];
}

export interface FeatureGroup {
  source: string; // include filename, or "(this file)" for local defs
  names: string[];
}

export interface FeatureNamesResponse {
  names: string[];
  groups: FeatureGroup[];
}

export interface SimplifyChange {
  kind: string; // collinear-node, covered-spur, collinear-point, …
  target: string; // "corridor.c97" / "room.hall"
  message: string;
  line: number;
  applied: boolean; // false: a suggestion left alone (message says why)
}

export interface SimplifyResponse {
  source: string;
  changed: boolean;
  changes: SimplifyChange[];
  // target -> {"nodes"|"segments"|"points": {before, after}}
  stats: Record<string, Record<string, { before: number; after: number }>>;
  saved: boolean;
}

// Minimal shape of the parsed DungeonMap model. We only type the
// fields the web app actually consumes (the print view); other
// fields are left as `unknown` to avoid drifting out of sync.
export interface ParsedFeatureInstance {
  ref: string;
  description?: string | null;
  dm_notes?: string | null;
}
export interface ParsedFeatureDef {
  name: string;
  display_name?: string | null;
  description?: string | null;
}
export interface ParsedRoom {
  name: string;
  label?: { text: string } | null;
  description?: string | null;
  dm_notes?: string | null;
  features: ParsedFeatureInstance[];
}
export interface ParsedLayer {
  name: string;
  hidden: boolean;
  rooms: ParsedRoom[];
}
export interface ParsedMapConfig {
  name: string;
  description?: string | null;
  dm_notes?: string | null;
}
export interface ParsedMap {
  map: ParsedMapConfig;
  feature_defs: Record<string, ParsedFeatureDef>;
  rooms: Record<string, ParsedRoom>;
  layers: ParsedLayer[];
}
