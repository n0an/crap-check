---
name: swift-crap-check
description: Rank Swift functions by the CRAP metric - cyclomatic complexity weighted against test coverage - and drive the risky ones under threshold. Use for change-risk audits, complexity/coverage reports, deciding what to test or split before a refactor, gating a CI job, or when the user mentions CRAP, cyclomatic complexity, code risk, or "what is dangerous to change here".
license: MIT
argument-hint: "[target or scheme] [--threshold N]"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash]
metadata:
  author: Anton Novoselov
  version: "1.0"
---

# Swift CRAP Check

Rank Swift functions by how risky they are to change, then drive that risk down.

CRAP (Change Risk Anti-Patterns) combines cyclomatic complexity with test coverage:

```
crap = complexity^2 * (1 - coverage)^3 + complexity
```

A fully covered function scores exactly its complexity. An uncovered one is punished cubically: complexity 12 at 0% coverage scores 156. The metric does not claim the code is bad, it claims the code is dangerous to change. That is what makes it a usable target, because there are only two ways down: add tests, or split the function.

Default threshold: 6.

## Steps

### 1. Report complexity per function

Two interchangeable sources. Pick by what is already installed.

**SwiftLint** (sharper: it sees closures as their own units). It reports violations only, so drop the threshold to 1 to make every branching function show up. Write `.crap-swiftlint.yml` at the repo root:

```yaml
only_rules:
  - cyclomatic_complexity
cyclomatic_complexity:
  warning: 1
  error: 10000
excluded:
  - .build
  - DerivedData
  - Tests
```

```bash
mkdir -p .crap
swiftlint lint --quiet --config .crap-swiftlint.yml --reporter json > .crap/lint.json
```

The high `error` value keeps the exit code at 0 so the run does not abort. Done when `.crap/lint.json` is a non-empty JSON array.

**lizard** (no SwiftLint, no Swift toolchain - pure Python, so it also runs on Linux CI):

```bash
mkdir -p .crap
python3 -m venv .crap/venv && .crap/venv/bin/pip install -q lizard
.crap/venv/bin/lizard --csv Sources > .crap/lizard.csv
```

Done when `.crap/lizard.csv` has one row per function. It reports every function including complexity 1, and needs no threshold trick.

The two differ in one way that matters: lizard folds a closure's complexity into its enclosing function, while SwiftLint scores the closure separately. A fat closure inside a thin function hides in lizard's average. Prefer SwiftLint when it is available.

### 2. Export per-function coverage

For a SwiftPM package:

```bash
swift test --enable-code-coverage
BIN=$(find .build/debug -name '*.xctest' -print -quit)
[ -d "$BIN/Contents/MacOS" ] && BIN="$BIN/Contents/MacOS/$(basename "$BIN" .xctest)"
xcrun llvm-cov export -instr-profile .build/debug/codecov/default.profdata "$BIN" > .crap/cov.json
```

For an Xcode scheme:

```bash
xcodebuild test -scheme "$SCHEME" -destination 'platform=iOS Simulator,name=iPhone 16' \
  -enableCodeCoverage YES -derivedDataPath .crap/dd
PROF=$(find .crap/dd -name '*.profdata' -print -quit)
APP=$(find .crap/dd/Build/Products -type d -name '*.app' -print -quit)
xcrun llvm-cov export -instr-profile "$PROF" "$APP/$(basename "$APP" .app)" > .crap/cov.json
```

Never pass `--summary-only`. It strips the per-function data the join depends on, and every function would silently read as 0% covered. The script rejects such a file rather than scoring it.

Done when `.crap/cov.json` contains a non-empty `functions` array.

### 3. Score

```bash
# whichever source step 1 produced
python3 scripts/crap.py --lint   .crap/lint.json   --coverage .crap/cov.json --threshold 6
python3 scripts/crap.py --lizard .crap/lizard.csv  --coverage .crap/cov.json --threshold 6
```

Exit code 1 means at least one function is over. `--json` gives machine-readable output for a loop, `--all` lists passing functions too.

Read the warnings before acting on the table. `not in the coverage report` means the test run never loaded that file, so its 0% is a build artifact rather than a testing gap. Fix that before treating the row as real.

### 4. Drive the offenders down

Take the worst score first, one function per iteration, and let the metric choose the fix:

- Low coverage with moderate complexity: write the missing tests. Coverage is cubed, so this collapses the score fastest and is almost always the first move.
- Still above threshold at full coverage: complexity is now the entire score. Split the function.
- Rerun steps 1-3 after every change. Never edit two functions before rescoring, or you cannot tell which edit helped.

Stop when the script exits 0. Report the before/after table rather than a narrative of the work.

### 5. Review structure, not syntax

Reading the resulting diff line by line defeats the purpose of having a metric. Check instead that:

- the extracted functions have names that say what they do
- each one sits in the module that owns the data it touches
- the new tests are named for a behaviour, not `testFoo2`

If those three hold, the score is trustworthy and the diff does not need line-by-line review.

## Limits worth knowing before trusting a number

- With SwiftLint as the source, functions of complexity 1 never appear. They cannot exceed CRAP 2, so nothing is lost.
- Coverage here is region-based, not line-based. A region is roughly a branch arm, so these numbers run closer to branch coverage than to the percentage Xcode displays, and will read lower.
- Complexity is joined to coverage by source line, innermost enclosing function wins. That is right for nested functions and closures, but a SwiftUI `body` full of trailing closures can attribute a violation to a closure instead of the view. Exclude generated and view-heavy files if they crowd the list.
- A file that appears in the complexity report but not in the coverage export scores 0% and sorts to the top. Treat that as a build problem first.
- Function names print mangled unless `swift demangle` is on `PATH`.

## Origin

Robert C. Martin described this loop on Kent C. Dodds' podcast: hand the agent a CRAP target of 6 and let it reason its own way there, discovering that it needs tests to cover the function and then that it still has to split it. The point is not the metric. The point is that the agent can check its own work without a human reading the code.
