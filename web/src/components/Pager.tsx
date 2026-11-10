import { useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useT } from "../i18n";

/** The page (from 0) kept in memory. */
function useMemoryPage(): [number, (page: number) => void] {
  return useState(0);
}

/** The page (from 0) kept in the address as `?<param>=<n>` from 1; the first page drops the parameter, and the
 * others in the address stay. A value that isn't a whole number reads as the first page. */
function useAddressPage(param: string): [number, (page: number) => void] {
  const [params, setParams] = useSearchParams();
  const raw = Number(params.get(param));
  const page = Number.isInteger(raw) && raw > 1 ? raw - 1 : 0;
  const set = (next: number) =>
    setParams(
      (current) => {
        const kept = new URLSearchParams(current);
        if (next > 0) kept.set(param, String(next + 1));
        else kept.delete(param);
        return kept;
      },
      { replace: false },
    );
  return [page, set];
}

/**
 * A long list shown a page at a time: `shown` is this page's items, and `pager` the Previous / Next row that says
 * which ones show ("21–40 of 45"), or nothing when everything fits on one page. A page that no longer exists after
 * rows went away is the last one. `label` names the pager for a screen reader. With `param` (pagination, 2026-10-23)
 * the page is kept in the address (`?page=3`), so Back and a reload come back to it; it must not change between
 * renders, and the list must be under a router.
 */
export function usePages<T>(
  items: T[],
  size = 20,
  label?: string,
  options: { param?: string } = {},
): { shown: T[]; pager: ReactNode } {
  const t = useT();
  const [wanted, setPage] = options.param ? useAddressPage(options.param) : useMemoryPage();
  const last = Math.max(0, Math.ceil(items.length / size) - 1);
  const page = Math.min(wanted, last);
  const shown = items.slice(page * size, (page + 1) * size);
  if (items.length <= size) return { shown, pager: null };
  const range = t("pager.range", {
    from: String(page * size + 1),
    to: String(page * size + shown.length),
    total: String(items.length),
  });
  return {
    shown,
    pager: (
      <nav className="pager" aria-label={label ?? t("pager.label")}>
        <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
          {t("pager.previous")}
        </button>
        <span className="pager-range">{range}</span>
        <button type="button" disabled={page === last} onClick={() => setPage(page + 1)}>
          {t("pager.next")}
        </button>
      </nav>
    ),
  };
}
