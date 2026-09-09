<h1 align="center">CRAP Check</h1>

<p align="center">
    <img src="https://img.shields.io/badge/metric-CRAP-e8590c.svg" alt="CRAP metric" />
    <img src="https://img.shields.io/badge/threshold-6-2d7ff9.svg" alt="Default threshold 6" />
    <img src="https://img.shields.io/badge/complexity-lizard-5cb85c.svg" alt="lizard complexity" />
    <img src="https://img.shields.io/badge/coverage-lcov%20%7C%20Cobertura%20%7C%20llvm--cov-F05138.svg" alt="lcov, Cobertura, llvm-cov" />
    <img src="https://img.shields.io/badge/version-2.0.0-blueviolet.svg" alt="Version 2.0.0" />
    <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="MIT License" />
    <a href="https://agentskills.io/home">
        <img src="https://img.shields.io/badge/Agent%20Skills-Compatible-purple.svg" alt="Agent Skills Compatible" />
    </a>
</p>

> **📐 "Complex" is not actionable. "Dangerous to change" is.** Based on Robert C. Martin's (Uncle Bob) description of how he codes with agents ([interview, 2026](https://www.youtube.com/watch?v=RxxxGkFIUJ0)).

An agent skill that helps AI coding agents like Claude Code, Codex, Cursor, and Gemini find the functions that are genuinely risky to modify, and then drive that risk down - by writing the missing tests or splitting the function, whichever the number says.

It uses the [Agent Skills](https://agentskills.io/home) format, so it works smoothly with Claude Code, Codex, Gemini, Cursor, and more.

CRAP (Change Risk Anti-Patterns, Agitar Software, 2007) weighs cyclomatic complexity against test coverage:

```
crap = complexity² × (1 − coverage)³ + complexity
```

The cube is the whole idea. A function of complexity 12 scores **156** with no tests and exactly **12** with full coverage. Same code, same complexity - but one of them you can refactor tonight and the other one will bite you. The metric does not say the code is bad, it says the code is *unsafe to touch*, and that is something an agent can actually act on.

```
   CRAP   CX     COV  LOCATION
   52.2!  10   25.0%  sample.py:10   classify
   16.0!   8   50.0%  sync.ts:140    applyPatch
   12.0!  12  100.0%  SyncEngine.swift:40   resolveConflicts
```


## What It Covers

- **The scoring loop** - report complexity for every function, export coverage, join them, and rank by change risk with a hard exit code so an agent or a CI job can loop on it
- **lizard as the default complexity source** - pure Python, 27 languages, real line spans, no compiler. SwiftLint remains an optional Swift-only bonus because it scores closures as their own units
- **Three coverage inputs** - lcov `.info` (JS/TS, Python, gcov, Go via a converter), Cobertura XML (Java/Kotlin/.NET), llvm-cov JSON (Swift/ObjC/C/C++/Rust on LLVM). Line-based coverage joins against lizard's span; llvm-cov still joins by innermost function region
- **A line-based join, not a name-based one** - nested functions attach to the right owner, and generics do not break the match
- **How to pick the fix** - coverage is cubed and complexity is only squared, so tests collapse the score faster than extraction. Still over threshold at 100% coverage means complexity is the entire score, and only then is it time to split
- **The traps that produce confident nonsense** - `llvm-cov --summary-only` silently reads as 0% coverage across the board (the script hard-rejects it), a regex over `if`/`for`/`while` inflates CRAP because complexity is squared (do not do this), and a file missing from the coverage export sorts to the top as a build problem rather than a testing gap
- **Reviewing the result** - three structural checks on the diff that make the score trustworthy, instead of reading the refactor line by line and defeating the point of having a metric


## Installing

You can install this skill into Claude Code, Codex, Gemini, Cursor, and more by using `npx`:

```bash
npx skills add https://github.com/n0an/crap-check --skill crap-check
```

If you get the error `npx: command not found`, it means you do not currently have Node installed. You need to run this command to install Node through Homebrew:

```bash
brew install node
```

And if that fails, it usually means you need to [install Homebrew](https://brew.sh) first.

When using `npx`, you can select exactly which agents you want to use during the installation. You can also select whether the skill should be installed just for one project, or whether it should be made available for all your projects.

### Alternative install methods

**Claude Code:**

```bash
/plugin install n0an/crap-check
```

**Gemini:**

```bash
gemini extensions install https://github.com/n0an/crap-check.git --consent
```

Alternatively, you can clone this whole repository and install it however you want.

### Tooling in the target project

Complexity:

```bash
pip install lizard              # default, 27 languages, no toolchain
brew install swiftlint          # optional Swift bonus, sees closures separately
```

Coverage is whatever the repo already produces: lcov, Cobertura, or `llvm-cov export` (not `--summary-only`).

For Swift, run the scoring step on a machine that has `swift` on `PATH`. llvm-cov reports mangled symbols and demangling shells out to `swift demangle`; without it the scores are still correct but names print as `$s5AIKit12TextEnhancerV7enhance...` instead of `AIKit.TextEnhancer.enhance(...)`.


## Using CRAP Check

The skill is called CRAP Check, and can be triggered in various ways. For example, in Claude Code you would use this:

> /crap-check

And in Codex you would use this:

> $crap-check

You can also trigger the skill using natural language:

> What is riskiest to change in this module?

> Get everything in src/ under a CRAP of 6.

> Run a complexity and coverage audit before I start this refactor.

The scoring script is standalone and works without any agent:

```bash
python3 crap-check/scripts/crap.py \
  --lizard .crap/lizard.csv --lcov .crap/coverage.info --threshold 6
```

It exits 1 when anything is over the threshold, so it drops straight into CI. `--json` gives machine-readable output for an agent loop, and `--all` lists the passing functions too.


## Why Use an Agent Skill for This?

Ask an agent to "reduce complexity" and it will extract three helper functions, report success, and leave the risk exactly where it was - because nothing measured whether the code was safe to change in the first place.

This skill:

- **Gives the agent a number to close, not an adjective to interpret** - one score per function, one threshold, one exit code
- **Makes the metric choose the fix** - the coverage term is cubed and the complexity term is squared, so the score itself says whether to write tests or to split, and the agent stops guessing
- **Attributes complexity to the right function** - the join is by source line span, so nested functions do not get scored against their parent
- **Refuses to score a broken input** - a `--summary-only` coverage export looks valid and reads as zero coverage everywhere, which would make a well-tested project look catastrophic; the script fails loudly instead
- **Separates a testing gap from a build problem** - a file missing from the coverage export is flagged, not silently ranked worst
- **Ends with a structural review, not a line-by-line one** - if the extracted names, module placement, and test names hold up, the diff does not need reading

The deeper point, and Uncle Bob's on that podcast: the agent can check its own work here. A human does not have to read the code to know whether the risk went down.


## Repository layout

```
crap-check/                          the portable Agent Skills folder
├── SKILL.md                         the workflow: sources, join, scoring, the repair loop
├── scripts/crap.py                  the scorer - joins complexity to coverage, ranks by CRAP
└── agents/openai.yaml               Codex interface metadata
tests/test_crap.py                   fixture tests (lcov, Cobertura, llvm-cov, SwiftLint)
.claude-plugin/plugin.json           the plugin manifest
gemini-extension.json                the Gemini extension manifest
```

Everything the skill needs lives inside `crap-check/`, so a standalone [Agent Skills](https://agentskills.io/home) install is self-contained - `SKILL.md` addresses its files as `scripts/...`, with no path reaching outside the skill folder.

Related: [agent-gauntlet](https://github.com/n0an/agent-gauntlet) uses a CRAP threshold as one gate inside a five-stage pipeline. This repo is the metric on its own, for when you want the audit without the pipeline.


## Contributing

Contributions are welcome - whether adding a coverage parser, sharpening the join, or fixing typos.

- Keep Markdown concise. There is a token cost to using skills, so respect the token budgets of users.
- Do not repeat things LLMs already know. Focus on the join mechanics, the thresholds, and the failure modes that produce confidently wrong numbers.
- The scorer must stay deterministic: one command, one hard exit code, runnable in a loop.
- All work must be licensed under the MIT license.


## License

Available under the [MIT License](LICENSE), which permits commercial use, modification, distribution, and private use.
