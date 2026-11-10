"""python -m evals [--case ID] [--fixture PATH] [--live [--compare-ttrpg2] ...]; see evals/README.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals import cases as _cases
from evals import runner


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m evals")
    p.add_argument("--case", action="append", help="case id (repeatable; default all)")
    p.add_argument("--fixture", type=Path, help="check one transcript against --case")
    p.add_argument("--list", action="store_true", help="list cases and fixtures")
    live = p.add_argument_group("live mode (opt-in: runs the real claude -p, costs tokens)")
    live.add_argument(
        "--live",
        action="store_true",
        help="play the case's beats through Delve's claude -p provider and record a fixture (or set DELVE_EVAL_LIVE=1)",
    )
    live.add_argument("--model", help="the DM's model (default: the provider's default)")
    live.add_argument("--effort", help="low, medium, high, max or auto (default: auto)")
    live.add_argument(
        "--compare-ttrpg2",
        action="store_true",
        help="also play the same player lines through ttrpg2's live mode, side by side",
    )
    live.add_argument("--ttrpg2", type=Path, help="ttrpg2's checkout (default ~/claude/ttrpg2), read only")
    live.add_argument("--keep-data", action="store_true", help="keep the temp data dir")
    live.add_argument("--tone", help="the campaign's tone (default: the case's, else classic)")
    live.add_argument(
        "--xp",
        help="what earns XP, comma-separated (monsters,milestones,roleplay,gold,abilities; 'none' for nothing)",
    )
    a = p.parse_args(argv)

    all_cases = _cases.load_cases()
    ids = a.case or sorted(all_cases)
    unknown = [c for c in ids if c not in all_cases]
    if unknown:
        p.error(f"unknown case(s): {', '.join(unknown)}; have {', '.join(sorted(all_cases))}")

    if a.list:
        for cid in ids:
            print(f"{cid}: {all_cases[cid].get('description', '')}")
            for fx in _cases.fixtures(cid):
                print(f"    {fx.name}")
        return 0

    if runner.live_opted_in(a.live):
        return _live(a, [all_cases[cid] for cid in ids])

    if a.fixture:
        if len(ids) != 1:
            p.error("--fixture needs exactly one --case")
        results = [runner.run_fixture(all_cases[ids[0]], a.fixture)]
    else:
        results = runner.run_offline(ids)
    for r in results:
        print(r.summary())
    bad = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} fixtures as expected")
    return 1 if bad else 0


def _live(a: argparse.Namespace, cases: list[dict]) -> int:
    from evals import live
    from evals.trace import read_records

    for case in cases:
        print(f"{case['id']}: playing {len(case.get('beats') or [])} beat(s) through claude -p …", file=sys.stderr)
        out = live.run_live(case, model=a.model, effort=a.effort, keep_data=a.keep_data, settings=_settings(a))
        print(f"recorded {out}")
        print(runner.run_fixture(case, out).summary())
        theirs = None
        if a.compare_ttrpg2:
            ttrpg2 = a.ttrpg2 or live.TTRPG2
            theirs = live.run_ttrpg2(case, _cases.recording_dir(case["id"], "ttrpg2"), ttrpg2)
            if theirs is None:
                print(f"ttrpg2 has no case {case['id']!r} it can play; Delve only")
            else:
                print(f"ttrpg2 recorded {theirs['fixture']}, {len(theirs['findings'])} finding(s)")
                for finding in theirs["findings"]:
                    print(f"       {finding}")
        print(live.side_by_side(live.beat_report(read_records(out)), theirs and theirs["beats"]))
    return 0


def _settings(a: argparse.Namespace) -> dict:
    """The play settings asked for on the command line, over the case's own."""
    settings: dict = {}
    if a.tone:
        settings["tone"] = a.tone
    if a.xp:
        settings["xp_awards"] = [] if a.xp == "none" else [name.strip() for name in a.xp.split(",") if name.strip()]
    return settings


if __name__ == "__main__":
    sys.exit(main())
