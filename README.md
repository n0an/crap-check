<h1 align="center">Swift CRAP Check</h1>

<p align="center">
    <img src="https://img.shields.io/badge/metric-CRAP-e8590c.svg" alt="CRAP metric" />
    <img src="https://img.shields.io/badge/threshold-6-2d7ff9.svg" alt="Default threshold 6" />
    <img src="https://img.shields.io/badge/complexity-SwiftLint%20or%20lizard-5cb85c.svg" alt="SwiftLint or lizard" />
    <img src="https://img.shields.io/badge/coverage-llvm--cov-F05138.svg" alt="llvm-cov coverage" />
    <img src="https://img.shields.io/badge/version-1.0.0-blueviolet.svg" alt="Version 1.0.0" />
    <img src="https://img.shields.io/badge/license-MIT-lightgrey.svg" alt="MIT License" />
    <a href="https://agentskills.io/home">
        <img src="https://img.shields.io/badge/Agent%20Skills-Compatible-purple.svg" alt="Agent Skills Compatible" />
    </a>
</p>

> **📐 "Complex" is not actionable. "Dangerous to change" is.** Based on Robert C. Martin's (Uncle Bob) description of how he codes with agents ([interview, 2026](https://www.youtube.com/live/zcLPGC-tvgk)).

An agent skill that helps AI coding agents like Claude Code, Codex, Cursor, and Gemini find the Swift functions that are genuinely risky to modify, and then drive that risk down - by writing the missing tests or splitting the function, whichever the number says.

It uses the [Agent Skills](https://agentskills.io/home) format, so it works smoothly with Claude Code, Codex, Gemini, Cursor, and more.

CRAP (Change Risk Anti-Patterns, Agitar Software, 2007) weighs cyclomatic complexity against test coverage:

```
crap = complexity² × (1 − coverage)³ + complexity
```

The cube is the whole idea. A function of complexity 12 scores **156** with no tests and exactly **12** with full coverage. Same code, same complexity - but one of them you can refactor tonight and the other one will bite you. The metric does not say the code is bad, it says the code is *unsafe to touch*, and that is something an agent can actually act on.

```
   CRAP   CX     COV  LOCATION
  156.0!  12    0.0%  SyncEngine.swift:90   merge
   27.7!   7   25.0%  SyncEngine.swift:52   resolveConflicts closure
   16.0!   8   50.0%  SyncEngine.swift:140  applyPatch
   12.0!  12  100.0%  SyncEngine.swift:40   resolveConflicts

3 of 4 scored functions are above CRAP 6.
```


## What It Covers

- **The scoring loop** - report complexity for every function, export per-function coverage, join them, and rank by change risk with a hard exit code so an agent or a CI job can loop on it
- **Two complexity sources** - SwiftLint (sharper: it scores closures as their own units) or [lizard](https://github.com/terryyin/lizard) (pure Python, no SwiftLint and no Swift toolchain, so it also runs on Linux CI). The skill covers both and names the tradeoff between them
- **A line-based join, not a name-based one** - SwiftLint gives file plus line, llvm-cov gives the line span of each function's coverage regions, and the innermost enclosing span wins. Nested functions and closures attach to the right owner, and generics do not break the match
- **How to pick the fix** - coverage is cubed and complexity is only squared, so tests collapse the score faster than extraction. Still over threshold at 100% coverage means complexity is the entire score, and only then is it time to split
- **The traps that produce confident nonsense** - `llvm-cov --summary-only` silently reads as 0% coverage across the board (the script hard-rejects it), region coverage runs lower than the line percentage Xcode shows, and a file missing from the coverage export sorts to the top as a build problem rather than a testing gap
- **Reviewing the result** - three structural checks on the diff that make the score trustworthy, instead of reading the refactor line by line and defeating the point of having a metric


## Installing

You can install this skill into Claude Code, Codex, Gemini, Cursor, and more by using `npx`:

```bash
npx skills add https://github.com/n0an/swift-crap-check --skill swift-crap-check
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
/plugin install n0an/swift-crap-check
```

**Gemini:**

```bash
gemini extensions install https://github.com/n0an/swift-crap-check.git --consent
```

Alternatively, you can clone this whole repository and install it however you want.

### Tooling in the target project

Coverage needs the Xcode toolchain (`xcrun llvm-cov`), which ships with Xcode. For complexity, install **either**:

```bash
brew install swiftlint          # sharper, sees closures separately
pip install lizard              # no toolchain needed, runs anywhere
```


## Using Swift CRAP Check

The skill is called Swift CRAP Check, and can be triggered in various ways. For example, in Claude Code you would use this:

> /swift-crap-check

And in Codex you would use this:

> $swift-crap-check

You can also trigger the skill using natural language:

> What is riskiest to change in this module?

> Get everything in NetworkKit under a CRAP of 6.

> Run a complexity and coverage audit before I start this refactor.

The scoring script is standalone and works without any agent:

```bash
python3 swift-crap-check/scripts/crap.py \
  --lint .crap/lint.json --coverage .crap/cov.json --threshold 6
```

It exits 1 when anything is over the threshold, so it drops straight into CI. `--json` gives machine-readable output for an agent loop, and `--all` lists the passing functions too.


## Why Use an Agent Skill for This?

Ask an agent to "reduce complexity" and it will extract three helper functions, report success, and leave the risk exactly where it was - because nothing measured whether the code was safe to change in the first place.

This skill:

- **Gives the agent a number to close, not an adjective to interpret** - one score per function, one threshold, one exit code
- **Makes the metric choose the fix** - the coverage term is cubed and the complexity term is squared, so the score itself says whether to write tests or to split, and the agent stops guessing
- **Attributes complexity to the right function** - the join is by source line span, so closures and nested functions do not get scored against their parent
- **Refuses to score a broken input** - a `--summary-only` coverage export looks valid and reads as zero coverage everywhere, which would make a well-tested project look catastrophic; the script fails loudly instead
- **Separates a testing gap from a build problem** - a file missing from the coverage export is flagged, not silently ranked worst
- **Ends with a structural review, not a line-by-line one** - if the extracted names, module placement, and test names hold up, the diff does not need reading

The deeper point, and Uncle Bob's on that podcast: the agent can check its own work here. A human does not have to read the code to know whether the risk went down.


## Repository layout

```
swift-crap-check/                    the portable Agent Skills folder
├── SKILL.md                         the workflow: sources, join, scoring, the repair loop
├── scripts/crap.py                  the scorer - joins complexity to coverage, ranks by CRAP
└── agents/openai.yaml               Codex interface metadata
.claude-plugin/plugin.json           the plugin manifest
gemini-extension.json                the Gemini extension manifest
```

Everything the skill needs lives inside `swift-crap-check/`, so a standalone [Agent Skills](https://agentskills.io/home) install is self-contained - `SKILL.md` addresses its files as `scripts/...`, with no path reaching outside the skill folder.

Related: [agent-gauntlet](https://github.com/n0an/agent-gauntlet) uses a CRAP threshold as one gate inside a five-stage pipeline. This repo is the metric on its own, for when you want the audit without the pipeline.


## Contributing

Contributions are welcome - whether adding a complexity source for another language, sharpening the join, or fixing typos.

- Keep Markdown concise. There is a token cost to using skills, so respect the token budgets of users.
- Do not repeat things LLMs already know. Focus on the join mechanics, the thresholds, and the failure modes that produce confidently wrong numbers.
- The scorer must stay deterministic: one command, one hard exit code, runnable in a loop.
- All work must be licensed under the MIT license.


## License

Available under the [MIT License](LICENSE), which permits commercial use, modification, distribution, and private use.
