# One command, the same locally and in CI:  make ci

UV  ?= uv
NPM ?= npm
WEB := web

.PHONY: install build run ci e2e-browser help-shots evals evals-live dsl-reference convert-live

install:
	$(UV) sync
	$(UV) run delve pack install packs/osric
	cd $(WEB) && $(NPM) ci

build:
	cd $(WEB) && $(NPM) run build

run: build
	$(UV) run delve serve

ci:
	$(UV) run ruff check src tests evals packs
	$(UV) run lint-imports
	$(UV) run pytest -n auto --dist loadgroup
	cd $(WEB) && $(NPM) run typecheck && $(NPM) test && $(NPM) run build

# The play screen, the module editor, New module and the print page in Chromium against delve serve with a fake
# claude; not in ci. Screenshots go to web/e2e/screenshots/.
e2e-browser: build
	cd $(WEB) && npx playwright install chromium
	cd $(WEB) && DELVE_E2E_PYTHON="$(UV) run python" npx playwright test

# The help's pictures (DEL-212): help-shots.spec.ts against the same fake server, then WebP in web/public/help/.
help-shots: build
	cd $(WEB) && DELVE_HELP_SHOTS=1 DELVE_E2E_PYTHON="$(UV) run python" npx playwright test e2e/help-shots.spec.ts
	$(UV) run python scripts/help_images.py

# The eval report on its own, offline: every fixture with its findings (tests/test_evals_offline.py runs it in ci).
evals:
	$(UV) run python -m evals

# Opt-in, never in ci: plays the cases through the real `claude -p` and spends tokens. EVAL_ARGS passes options, e.g.
#   make evals-live EVAL_ARGS="--case locked_door --compare-ttrpg2"
evals-live:
	$(UV) run python -m evals --live $(EVAL_ARGS)

# Rebuild the map language reference the sketch and generation prompts carry, from docs/maps/ (a test checks it).
dsl-reference:
	$(UV) run python -c "from pathlib import Path; from delve.modules.books.sketch import write_dsl_reference; write_dsl_reference(Path('docs/maps'))"

# Opt-in, never in ci: converts a real module PDF with the real `claude` into a temporary data dir, and spends tokens.
# It prints the time of every call, the warnings and the word coverage, and leaves the module as a .dscn in
# evals/recordings/conversions/:  make convert-live PDF=book.pdf TITLE="The Sunken Shrine"
convert-live:
	@test -n "$(PDF)" || { echo 'usage: make convert-live PDF=<file> [TITLE=...]' >&2; exit 2; }
	$(UV) run python scripts/convert_live.py "$(PDF)" $(if $(TITLE),--title "$(TITLE)")
