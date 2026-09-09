---
name: crap-check
description: "CRAP metric, cyclomatic complexity, risky-to-change code, coverage audit. Ranks functions by change risk across languages and drives them under threshold."
license: MIT
argument-hint: "[path] [--threshold N]"
allowed-tools: [Read, Write, Edit, Glob, Grep, Bash]
metadata:
  author: Anton Novoselov
  version: "2.0"
---

# CRAP Check

Rank functions by how risky they are to change, then drive that risk down.

CRAP (Change Risk Anti-Patterns) combines cyclomatic complexity with test coverage:

```
crap = complexity^2 * (1 - coverage)^3 + complexity
```

A fully covered function scores exactly its complexity. An uncovered one is punished cubically: complexity 12 at 0% coverage scores 156. The metric does not claim the code is bad, it claims the code is dangerous to change. Two ways down: add tests, or split the function.

Default threshold: 6.

Do not approximate complexity with regex over `if`/`while`/`for`. CRAP squares complexity, so a comment or a string literal that contains those words inflates the score by more than the error in complexity. Use lizard (or SwiftLint for Swift).

## Steps

### 1. Report complexity per function

**Default: lizard.** Pure Python, 27 languages, real `start_line..end_line` spans. No compiler.

```bash
mkdir -p .crap
python3 -m venv .crap/venv && .crap/venv/bin/pip install -q lizard
.crap/venv/bin/lizard --csv src lib app > .crap/lizard.csv
```

Done when `.crap/lizard.csv` has one row per function.

**Swift-only bonus: SwiftLint.** Sharper on closures (scores them as their own units; lizard folds a closure into its parent). Reports violations only, so drop the threshold to 1:

```yaml
# .crap-swiftlint.yml
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
swiftlint lint --quiet --config .crap-swiftlint.yml --reporter json > .crap/lint.json
```

The high `error` value keeps the exit code at 0. Done when `.crap/lint.json` is a non-empty JSON array. Prefer SwiftLint when it is already installed; otherwise lizard.

### 2. Export coverage

Pick the exporter that matches the stack. Never mix them in one run.

**lcov** (JS/TS via nyc/jest/vitest, Python via `coverage.py`, C/C++ via gcov, Go via `go tool cover` plus a converter, or `llvm-cov export --format=lcov`):

```bash
# examples - use whatever already produces lcov in this repo
npx nyc report --reporter=lcovonly --temp-dir coverage/.tmp > .crap/coverage.info
# or: coverage xml is Cobertura; lcov is:
python3 -m coverage lcov -o .crap/coverage.info
```

Done when `.crap/coverage.info` contains `DA:<line>,<hits>` records.

**Cobertura XML** (Java/Kotlin/.NET):

```bash
# whatever the build already writes, often target/site/cobertura/coverage.xml
```

Done when the XML has `<line number="…" hits="…"/>` nodes.

**llvm-cov JSON** (Swift, ObjC, C, C++, Rust on an LLVM toolchain):

```bash
# SwiftPM
swift test --enable-code-coverage
BIN=$(find .build/debug -name '*.xctest' -print -quit)
[ -d "$BIN/Contents/MacOS" ] && BIN="$BIN/Contents/MacOS/$(basename "$BIN" .xctest)"
xcrun llvm-cov export -instr-profile .build/debug/codecov/default.profdata "$BIN" > .crap/cov.json
```

Never pass `--summary-only`. It strips per-function data and every function would silently read as 0% covered. The script rejects such a file.

Done when `.crap/cov.json` contains a non-empty `functions` array.

### 3. Score

```bash
python3 scripts/crap.py --lizard .crap/lizard.csv --lcov .crap/coverage.info --threshold 6
python3 scripts/crap.py --lizard .crap/lizard.csv --cobertura coverage.xml --threshold 6
python3 scripts/crap.py --lizard .crap/lizard.csv --coverage .crap/cov.json --threshold 6
python3 scripts/crap.py --lint   .crap/lint.json  --coverage .crap/cov.json --threshold 6
```

Exit code 1 means at least one function is over. `--json` is for a loop. `--all` lists passing functions too.

Read the warnings before acting. `not in the coverage report` means the test run never loaded that file, so 0% is a build artifact, not a testing gap.

### 4. Drive the offenders down

Take the worst score first, one function per iteration:

- Low coverage with moderate complexity: write the missing tests. Coverage is cubed, so this collapses the score fastest.
- Still above threshold at full coverage: complexity is now the entire score. Split the function.
- Rerun steps 1-3 after every change. Never edit two functions before rescoring.

Stop when the script exits 0. Report the before/after table, not a narrative of the work.

### 5. Review structure, not syntax

- extracted functions have names that say what they do
- each one sits in the module that owns the data it touches
- new tests are named for a behaviour, not `testFoo2`

If those three hold, the score is trustworthy and the diff does not need line-by-line review.

## Limits

- lizard folds closure complexity into the parent. SwiftLint does not. A fat closure inside a thin function hides in lizard's average.
- lcov/Cobertura coverage is line-based (executable lines inside the function span). llvm-cov coverage is region-based and reads closer to branch coverage, so those numbers run lower than the percentage an IDE shows.
- A file in the complexity report but not in the coverage export scores 0% and sorts to the top. Treat that as a build problem first.
- Swift function names print mangled unless `swift demangle` is on `PATH`. Other languages print lizard's name as-is.

## Origin

Robert C. Martin described this loop on Kent C. Dodds' podcast: hand the agent a CRAP target of 6 and let it reason its own way there. The point is not the metric. The point is that the agent can check its own work without a human reading the code.
