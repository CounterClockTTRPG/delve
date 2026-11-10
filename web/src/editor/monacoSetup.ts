// Monaco comes from the bundle, never from a CDN: @monaco-editor/react's loader
// would otherwise fetch it from jsdelivr, which the CSP refuses and an offline
// table doesn't have. The .dmap language needs only the core editor worker.
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";

self.MonacoEnvironment = {
  getWorker: () => new EditorWorker(),
};

loader.config({ monaco });
