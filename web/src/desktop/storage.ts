// The browser's local storage for per-browser conveniences (split widths), as a storage that never throws: a private
// window or blocked site data reads nothing and keeps nothing, and the page works as without it.
export const safeStorage: Pick<Storage, "getItem" | "setItem"> = {
  getItem(key) {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Kept for this page view only.
    }
  },
};
