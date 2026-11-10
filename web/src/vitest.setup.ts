import { addDictionary } from "./i18n";
import de from "./i18n/de.json";
import fr from "./i18n/fr.json";
import lv from "./i18n/lv.json";
import nl from "./i18n/nl.json";

// jsdom doesn't implement ResizeObserver; the editor's SvgPreview uses it purely to
// refit the pan/zoom stage on container resize, which tests don't exercise.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (typeof globalThis.ResizeObserver === "undefined") {
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
}

// A data router builds a Request for every navigation with jsdom's AbortSignal,
// which Node's Request refuses. Tests don't abort navigations, so drop the signal.
const NodeRequest = globalThis.Request;
globalThis.Request = class extends NodeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    const { signal: _signal, ...rest } = init ?? {};
    super(input, rest);
  }
} as typeof Request;

// ProseMirror (the module text editor) measures the selection to scroll it into view; jsdom has no layout.
const noRects = () => ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] }) as unknown as DOMRectList;
const noRect = () => new DOMRect(0, 0, 0, 0);
Range.prototype.getClientRects ??= noRects;
Range.prototype.getBoundingClientRect ??= noRect;
document.elementFromPoint ??= () => null;

// The dictionaries other than English load when a reader speaks one (DEL-240); tests have them all at once.
addDictionary("nl", nl);
addDictionary("fr", fr);
addDictionary("de", de);
addDictionary("lv", lv);
