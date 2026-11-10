"""Run eval cases offline against their fixtures (the default). Live recording through Delve's `claude -p` provider
is in `evals.live`, and runs only when asked."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from evals import cases as _cases
from evals.checks import Finding, run_checks
from evals.trace import Trace, load_trace


@dataclass
class Result:
    case: str
    fixture: Path
    expected: str
    """"pass" | "violates" | "report"."""
    check: str | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        failed = {f.check for f in self.findings}
        if self.expected == "pass":
            return not failed
        if self.expected == "violates":
            return failed == {self.check}
        return True

    def summary(self) -> str:
        tag = "rec " if self.expected == "report" else "ok  " if self.ok else "FAIL"
        want = {"pass": "clean", "violates": f"violates {self.check}", "report": "recorded"}[self.expected]
        lines = [f"{tag} {self.case}/{self.fixture.name} (expect {want}, {len(self.findings)} finding(s))"]
        lines += [f"       {f}" for f in self.findings]
        return "\n".join(lines)


def evaluate(case: dict, trace: Trace) -> list[Finding]:
    return run_checks(case, trace)


def run_fixture(case: dict, fixture: Path) -> Result:
    expected, check = _cases.expectation(fixture)
    return Result(case["id"], fixture, expected, check, evaluate(case, load_trace(fixture)))


def run_offline(case_ids=None) -> list[Result]:
    all_cases = _cases.load_cases()
    results = []
    for cid in case_ids or sorted(all_cases):
        case = all_cases[cid]
        for fx in _cases.fixtures(cid):
            results.append(run_fixture(case, fx))
    return results


def live_opted_in(flag: bool) -> bool:
    return flag or os.environ.get("DELVE_EVAL_LIVE") == "1"
