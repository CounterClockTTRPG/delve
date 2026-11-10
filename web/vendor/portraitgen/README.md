# portraitgen, vendored

`src/` is portraitgen's `src/` at the commit in `COMMIT`, copied unchanged with
`git -C /home/raf/claude/portraitgen archive <commit> src`, and `web/` its editor (`index.html`, `app.js`,
`style.css`), with `git -C /home/raf/claude/portraitgen archive <commit> web/index.html web/app.js web/style.css`. portraitgen is MIT (its `package.json`); it ships no
LICENSE file at that commit, so `LICENSE` here is the MIT text. Don't edit `src/`: copy a newer commit over it.

Delve imports it as `portraitgen` (the alias in `web/vite.config.ts`, the types in `web/src/portraitgen.d.ts`) from
`web/src/components/Portrait.tsx` and `web/src/campaign/PortraitEditor.tsx`. Never import `src/png-node.js`: it pulls
in resvg. The editor is built as a page of its own (`vite.config.ts`'s `rollupOptions.input`), served at
`/vendor/portraitgen/web/index.html`, which only Delve's own pages may frame (`delve/web/guard.py`): the sheet's Edit
portrait opens it on a portrait's traits in its address, and reads them back from there (DEL-238).
