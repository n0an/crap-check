#!/usr/bin/env python3
"""Compute the CRAP metric per function.

CRAP (Change Risk Anti-Patterns, Agitar Software ~2007):

    crap(m) = complexity(m)^2 * (1 - coverage(m))^3 + complexity(m)

Complexity comes from `lizard --csv` (27 languages, no toolchain) or, for
Swift, SwiftLint's cyclomatic_complexity JSON reporter. Coverage comes from
lcov `.info`, Cobertura XML, `llvm-cov export` JSON (Apple/LLVM), or an Xcode
`.xcresult` / `.xccovarchive` read through `xccov`.

The Xcode source matters for real iOS/macOS app projects. `llvm-cov export`
needs a `default.profdata`, which you get from `swift test` on the host - but an
app target cannot be built that way, and a package whose dependencies are
iOS-only cannot either. Those projects test through the simulator with
`xcodebuild test`, whose only coverage artifact is an `.xcresult`. Without
`--xcresult` the Swift half of this tool is unreachable for exactly the projects
most likely to want it.

Join is by source location. lizard and llvm-cov both give a line span;
SwiftLint gives a single line. A record belongs to the tightest coverage
span that contains that line, or, for line-based coverage, to the executable
lines inside the complexity span.

That asymmetry decides which pairings work. `--lint` is zero-width, so against
a LINE-based source (`--lcov`, `--cobertura`, `--xcresult`) it probes exactly
the declaration line, which is usually not executable - every function then
scores 0% and the run is worthless. Pair `--lint` with `--coverage`, whose
spans `find_owner` can search, and pair the line-based sources with `--lizard`,
which reports a real start and end line.

Usage:
    crap.py --lizard lizard.csv --lcov coverage.info [--threshold 6]
    crap.py --lizard lizard.csv --cobertura coverage.xml
    crap.py --lizard lizard.csv --coverage cov.json
    crap.py --lint   lint.json  --coverage cov.json
    crap.py --lizard lizard.csv --xcresult Build.xcresult [--xccov-include Sources/]

Exit code is 1 when at least one function scores above the threshold.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

COMPLEXITY_RE = re.compile(r"currently complexity is (\d+)")
CODE_REGION_KIND = 0


@dataclass
class Function:
    """One function as reported by llvm-cov."""

    name: str
    path: str
    start_line: int
    end_line: int
    covered_regions: int
    total_regions: int
    call_count: int

    @property
    def coverage(self) -> float:
        if self.total_regions == 0:
            return 0.0
        return self.covered_regions / self.total_regions

    @property
    def span(self) -> int:
        return self.end_line - self.start_line


@dataclass
class Unit:
    """A function to be scored, from whichever complexity source was used."""

    path: str
    start_line: int
    end_line: int
    complexity: int
    label: str


@dataclass
class Row:
    path: str
    line: int
    complexity: int
    coverage: float
    name: str
    matched: bool
    call_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def crap(self) -> float:
        c = float(self.complexity)
        return c * c * (1.0 - self.coverage) ** 3 + c


def normalize(path: str) -> str:
    """Resolve a path so coverage and complexity tools agree on it."""
    return os.path.realpath(os.path.expanduser(path))


def load_json(path: str) -> object:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        sys.exit(f"crap: no such file: {path}")
    except json.JSONDecodeError as exc:
        sys.exit(f"crap: {path} is not valid JSON: {exc}")


def parse_lint(payload: object) -> list[Unit]:
    """Extract functions from a SwiftLint JSON report.

    SwiftLint reports a single line per violation rather than a span, so the
    unit is zero-width and the coverage join probes that one line.
    """
    if not isinstance(payload, list):
        sys.exit("crap: expected a SwiftLint JSON array; run swiftlint --reporter json")

    out: list[Unit] = []
    for violation in payload:
        if not isinstance(violation, dict):
            continue
        if violation.get("rule_id") != "cyclomatic_complexity":
            continue
        match = COMPLEXITY_RE.search(violation.get("reason") or "")
        if not match:
            continue
        path = violation.get("file")
        line = violation.get("line")
        if not path or not isinstance(line, int):
            continue
        out.append(
            Unit(
                path=normalize(path),
                start_line=line,
                end_line=line,
                complexity=int(match.group(1)),
                label="",
            )
        )
    return out


def parse_lizard(path: str) -> list[Unit]:
    """Extract functions from `lizard --csv` output.

    The 11 columns are, in order: nloc, ccn, tokens, params, length, location,
    file, name, long_name, start_line, end_line. Unlike SwiftLint this covers
    every function, including ones with no branches, and gives a real span.
    """
    out: list[Unit] = []
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.reader(handle):
                if len(row) < 11:
                    continue
                try:
                    complexity = int(row[1])
                    start_line = int(row[9])
                    end_line = int(row[10])
                except ValueError:
                    continue
                out.append(
                    Unit(
                        path=normalize(row[6]),
                        start_line=start_line,
                        end_line=end_line,
                        complexity=complexity,
                        label=row[7],
                    )
                )
    except FileNotFoundError:
        sys.exit(f"crap: no such file: {path}")

    if not out:
        sys.exit(
            f"crap: no functions parsed from {path}. Generate it with "
            "`lizard --csv <sources> > lizard.csv`."
        )
    return out


def parse_llvm_cov(payload: object) -> dict[str, list[Function]]:
    """Extract per-function coverage from an llvm-cov export, keyed by path."""
    if not isinstance(payload, dict) or "data" not in payload:
        sys.exit(
            "crap: expected an llvm-cov export object; run "
            "`llvm-cov export` / `xcrun llvm-cov export` WITHOUT --summary-only"
        )

    by_path: dict[str, list[Function]] = {}
    for block in payload.get("data") or []:
        for raw in block.get("functions") or []:
            regions = raw.get("regions") or []
            filenames = raw.get("filenames") or []
            if not regions or not filenames:
                continue

            code_regions = [r for r in regions if len(r) > 7 and r[7] == CODE_REGION_KIND]
            if not code_regions:
                code_regions = [r for r in regions if len(r) >= 5]
            if not code_regions:
                continue

            path = normalize(filenames[0])
            fn = Function(
                name=raw.get("name") or "<anonymous>",
                path=path,
                start_line=min(r[0] for r in code_regions),
                end_line=max(r[2] for r in code_regions),
                covered_regions=sum(1 for r in code_regions if r[4] > 0),
                total_regions=len(code_regions),
                call_count=int(raw.get("count") or 0),
            )
            by_path.setdefault(path, []).append(fn)

    if not by_path:
        sys.exit(
            "crap: the coverage export contains no per-function data. Re-run "
            "`llvm-cov export` WITHOUT --summary-only."
        )
    return by_path


def parse_lcov(path: str) -> dict[str, dict[int, int]]:
    """Extract DA:<line>,<hits> records from an lcov .info file."""
    by_path: dict[str, dict[int, int]] = {}
    current: str | None = None
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if line.startswith("SF:"):
                    current = normalize(line[3:])
                    by_path.setdefault(current, {})
                elif line.startswith("DA:") and current:
                    parts = line[3:].split(",")
                    if len(parts) < 2:
                        continue
                    try:
                        lineno = int(parts[0])
                        hits = int(float(parts[1]))
                    except ValueError:
                        continue
                    by_path[current][lineno] = hits
                elif line == "end_of_record":
                    current = None
    except FileNotFoundError:
        sys.exit(f"crap: no such file: {path}")

    by_path = {p: hits for p, hits in by_path.items() if hits}
    if not by_path:
        sys.exit(
            f"crap: no DA line records in {path}. Export lcov with "
            "line data (nyc/jest, coverage.py --format=lcov, "
            "llvm-cov export --format=lcov, gcov)."
        )
    return by_path


def parse_cobertura(path: str) -> dict[str, dict[int, int]]:
    """Extract line hits from Cobertura XML (Java/Kotlin/.NET and friends)."""
    try:
        tree = ET.parse(path)
    except FileNotFoundError:
        sys.exit(f"crap: no such file: {path}")
    except ET.ParseError as exc:
        sys.exit(f"crap: {path} is not valid Cobertura XML: {exc}")

    by_path: dict[str, dict[int, int]] = {}
    for cls in tree.iter():
        if not cls.tag.endswith("class"):
            continue
        filename = cls.get("filename") or cls.get("name")
        if not filename:
            continue
        hits: dict[int, int] = by_path.setdefault(normalize(filename), {})
        for node in cls.iter():
            if not node.tag.endswith("line"):
                continue
            number = node.get("number")
            if not number:
                continue
            try:
                hits[int(number)] = int(float(node.get("hits") or 0))
            except ValueError:
                continue

    by_path = {p: hits for p, hits in by_path.items() if hits}
    if not by_path:
        sys.exit(f"crap: no line records in {path}. Expected Cobertura XML.")
    return by_path


def xccov_hits(payload: object) -> dict[str, dict[int, int]]:
    """Convert one `xccov view --file --json` payload into line hits.

    The payload is `{"<path>": [{"line": 1, "isExecutable": false}, ...]}`.
    Non-executable lines carry no `executionCount` and are dropped, so the
    result has the same meaning as lcov's DA records: executable lines only,
    mapped to their hit count.
    """
    out: dict[str, dict[int, int]] = {}
    if not isinstance(payload, dict):
        return out
    for path, rows in payload.items():
        if not isinstance(rows, list):
            continue
        hits: dict[int, int] = {}
        for row in rows:
            if not isinstance(row, dict) or not row.get("isExecutable"):
                continue
            line = row.get("line")
            if not isinstance(line, int):
                continue
            hits[line] = int(row.get("executionCount") or 0)
        if hits:
            out[normalize(path)] = hits
    return out


def xccov_argv(bundle: str, rest: list[str]) -> list[str]:
    """`xccov view` argv for a bundle.

    An `.xcresult` needs `--archive` to reach its coverage archive; an
    `.xccovarchive` IS one and rejects the flag. Getting this wrong reports
    `unrecognized file format`, which reads like a corrupt bundle.
    """
    prefix = ["xcrun", "xccov", "view"]
    if bundle.rstrip("/").endswith(".xccovarchive"):
        return prefix + rest + [bundle]
    return prefix + ["--archive"] + rest + [bundle]


def xccov_run(argv: list[str], timeout: int = 120) -> str | None:
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def parse_xccov(
    bundle: str, include: list[str] | None = None, jobs: int = 8
) -> dict[str, dict[int, int]]:
    """Extract line hits from an Xcode `.xcresult` / `.xccovarchive`.

    `xccov` has no whole-bundle line dump: `--file-list` enumerates paths and
    each file's hits need their own invocation. That is ~0.7s per file, so a
    real app bundle (800+ files) takes minutes single-threaded - hence the
    thread pool and `--xccov-include`. The work is subprocess-bound, so threads
    are the right tool despite the GIL.
    """
    if not os.path.exists(bundle):
        sys.exit(f"crap: no such file: {bundle}")
    if not shutil.which("xcrun"):
        sys.exit(
            "crap: --xcresult needs Xcode's `xccov`, which is macOS-only. On "
            "other platforms export lcov or Cobertura instead."
        )

    listing = xccov_run(xccov_argv(bundle, ["--file-list"]))
    if listing is None:
        sys.exit(
            f"crap: could not read a coverage archive from {bundle}. For an "
            ".xcresult, confirm the tests ran with `-enableCodeCoverage YES`."
        )

    paths = [line.strip() for line in listing.splitlines() if line.strip()]
    if include:
        paths = [p for p in paths if any(token in p for token in include)]
    if not paths:
        sys.exit(
            f"crap: no files in {bundle} matched. Drop or widen --xccov-include."
        )

    def one(path: str) -> dict[str, dict[int, int]]:
        # The archive's own spelling of the path is required: --file with a
        # path that only looks right fails with "Failed to find coverage lines".
        raw = xccov_run(xccov_argv(bundle, ["--file", path, "--json"]))
        if raw is None:
            return {}
        try:
            return xccov_hits(json.loads(raw))
        except json.JSONDecodeError:
            return {}

    by_path: dict[str, dict[int, int]] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        for chunk in pool.map(one, paths):
            by_path.update(chunk)

    if not by_path:
        sys.exit(
            f"crap: no executable lines found in {bundle}. Confirm the test run "
            "produced coverage for the targets you are scoring."
        )
    return by_path


def find_owner(functions: list[Function], line: int) -> Function | None:
    """Return the innermost function whose region span contains `line`."""
    containing = [f for f in functions if f.start_line <= line <= f.end_line]
    if not containing:
        return None
    return min(containing, key=lambda f: (f.span, f.start_line))


def resolve_path(
    unit_path: str, available: dict[str, object]
) -> tuple[str | None, list[str]]:
    """Match a complexity path to a coverage path; fall back to basename."""
    if unit_path in available:
        return unit_path, []
    by_base: dict[str, list[str]] = {}
    for path in available:
        by_base.setdefault(os.path.basename(path), []).append(path)
    matches = by_base.get(os.path.basename(unit_path), [])
    if len(matches) == 1:
        return matches[0], ["matched by filename, not full path"]
    return None, []


def build_rows_llvm(units: list[Unit], coverage: dict[str, list[Function]]) -> list[Row]:
    rows: list[Row] = []
    for unit in units:
        path, warnings = resolve_path(unit.path, coverage)
        functions = coverage.get(path) if path else None
        owner = find_owner(functions, unit.start_line) if functions else None
        if owner is None:
            rows.append(
                Row(
                    path=unit.path,
                    line=unit.start_line,
                    complexity=unit.complexity,
                    coverage=0.0,
                    name=unit.label or "<no coverage data>",
                    matched=False,
                    warnings=["not in the coverage report; scored as 0% covered"],
                )
            )
            continue
        rows.append(
            Row(
                path=unit.path,
                line=unit.start_line,
                complexity=unit.complexity,
                coverage=owner.coverage,
                name=owner.name,
                matched=True,
                call_count=owner.call_count,
                warnings=warnings,
            )
        )
    rows.sort(key=lambda r: (-r.crap, r.path, r.line))
    return rows


def build_rows_lines(units: list[Unit], line_hits: dict[str, dict[int, int]]) -> list[Row]:
    """Join complexity spans to lcov/Cobertura line hits."""
    rows: list[Row] = []
    for unit in units:
        path, warnings = resolve_path(unit.path, line_hits)
        hits = line_hits.get(path) if path else None
        if not hits:
            rows.append(
                Row(
                    path=unit.path,
                    line=unit.start_line,
                    complexity=unit.complexity,
                    coverage=0.0,
                    name=unit.label or "<no coverage data>",
                    matched=False,
                    warnings=["not in the coverage report; scored as 0% covered"],
                )
            )
            continue
        span = {
            lineno: count
            for lineno, count in hits.items()
            if unit.start_line <= lineno <= unit.end_line
        }
        if not span:
            rows.append(
                Row(
                    path=unit.path,
                    line=unit.start_line,
                    complexity=unit.complexity,
                    coverage=0.0,
                    name=unit.label or "<no coverage data>",
                    matched=False,
                    warnings=[
                        "no executable lines in this span; scored as 0% covered"
                        + (
                            " - a zero-width --lint unit against line-based "
                            "coverage; use --lizard for a real span"
                            if unit.start_line == unit.end_line
                            else ""
                        )
                    ],
                )
            )
            continue
        covered = sum(1 for count in span.values() if count > 0)
        rows.append(
            Row(
                path=unit.path,
                line=unit.start_line,
                complexity=unit.complexity,
                coverage=covered / len(span),
                name=unit.label or "<line coverage>",
                matched=True,
                warnings=warnings,
            )
        )
    rows.sort(key=lambda r: (-r.crap, r.path, r.line))
    return rows


def demangle(names: list[str]) -> dict[str, str]:
    """Best-effort Swift demangling; returns the input unchanged if swift is absent."""
    unique = [n for n in dict.fromkeys(names) if n.startswith("$s") or n.startswith("_$s")]
    if not unique or not shutil.which("swift"):
        return {}
    try:
        result = subprocess.run(
            ["swift", "demangle", "--compact", "--"] + unique,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    lines = result.stdout.strip().splitlines()
    if len(lines) != len(unique):
        return {}
    return dict(zip(unique, (line.strip() for line in lines)))


def shorten(name: str, width: int = 58) -> str:
    if len(name) <= width:
        return name
    return name[: width - 1] + "…"


def render_table(rows: list[Row], threshold: float, pretty: dict[str, str]) -> str:
    if not rows:
        return "No functions to score.\n"

    lines = [
        f"{'CRAP':>7}  {'CX':>3}  {'COV':>6}  LOCATION",
        f"{'-' * 7}  {'-' * 3}  {'-' * 6}  {'-' * 60}",
    ]
    for row in rows:
        flag = "!" if row.crap > threshold else " "
        location = f"{os.path.basename(row.path)}:{row.line}"
        name = shorten(pretty.get(row.name, row.name))
        lines.append(
            f"{row.crap:>7.1f}{flag} {row.complexity:>3}  "
            f"{row.coverage * 100:>5.1f}%  {location}  {name}"
        )
        for warning in row.warnings:
            lines.append(f"{'':>7}   {'':>3}  {'':>6}  ↳ {warning}")

    over = [r for r in rows if r.crap > threshold]
    lines.append("")
    lines.append(
        f"{len(over)} of {len(rows)} scored functions are above CRAP {threshold:g}."
    )
    if over:
        worst = over[0]
        lines.append(
            f"Worst: {os.path.basename(worst.path)}:{worst.line} "
            f"at {worst.crap:.1f} (complexity {worst.complexity}, "
            f"coverage {worst.coverage * 100:.1f}%)."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compute the CRAP metric per function from complexity + coverage."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--lizard",
        help="lizard --csv output (default complexity source; 27 languages)",
    )
    source.add_argument("--lint", help="swiftlint --reporter json output (Swift only)")
    coverage = parser.add_mutually_exclusive_group(required=True)
    coverage.add_argument("--lcov", help="lcov .info file (line hits)")
    coverage.add_argument("--cobertura", help="Cobertura XML (line hits)")
    coverage.add_argument(
        "--coverage",
        help="llvm-cov export JSON (not --summary-only); Apple/LLVM stack",
    )
    coverage.add_argument(
        "--xcresult",
        help="Xcode .xcresult or .xccovarchive, read via xccov (macOS only)",
    )
    parser.add_argument(
        "--xccov-include",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="with --xcresult, only read paths containing this; repeatable. "
        "A whole app bundle is 800+ files at ~0.7s each",
    )
    parser.add_argument(
        "--xccov-jobs",
        type=int,
        default=8,
        help="with --xcresult, parallel xccov invocations (default 8)",
    )
    parser.add_argument(
        "--threshold", type=float, default=6.0, help="fail above this CRAP score (default 6)"
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    parser.add_argument(
        "--all", action="store_true", help="list every scored function, not just those over threshold"
    )
    args = parser.parse_args(argv)

    if args.lizard:
        units = parse_lizard(args.lizard)
    else:
        units = parse_lint(load_json(args.lint))

    if args.lcov:
        rows = build_rows_lines(units, parse_lcov(args.lcov))
    elif args.cobertura:
        rows = build_rows_lines(units, parse_cobertura(args.cobertura))
    elif args.xcresult:
        rows = build_rows_lines(
            units,
            parse_xccov(args.xcresult, args.xccov_include, args.xccov_jobs),
        )
    else:
        rows = build_rows_llvm(units, parse_llvm_cov(load_json(args.coverage)))

    unmatched = sum(1 for r in rows if not r.matched)
    over = [r for r in rows if r.crap > args.threshold]
    shown = rows if args.all else (over or rows)

    if args.json:
        print(
            json.dumps(
                {
                    "threshold": args.threshold,
                    "scored": len(rows),
                    "over_threshold": len(over),
                    "unmatched": unmatched,
                    "functions": [
                        {
                            "crap": round(r.crap, 2),
                            "complexity": r.complexity,
                            "coverage": round(r.coverage, 4),
                            "file": r.path,
                            "line": r.line,
                            "name": r.name,
                            "matched_coverage": r.matched,
                            "call_count": r.call_count,
                            "warnings": r.warnings,
                        }
                        for r in shown
                    ],
                },
                indent=2,
            )
        )
    else:
        pretty = demangle([r.name for r in shown])
        sys.stdout.write(render_table(shown, args.threshold, pretty))
        if unmatched:
            sys.stdout.write(
                f"\n{unmatched} function(s) had no coverage data and were scored as 0% "
                "covered. Confirm the test run actually exercised that target.\n"
            )

    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
