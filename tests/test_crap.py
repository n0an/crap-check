#!/usr/bin/env python3
"""Fixture tests for crap.py. Run: python3 tests/test_crap.py"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "crap-check" / "scripts" / "crap.py"
sys.path.insert(0, str(SCRIPT.parent))
import crap  # noqa: E402


def crap_of(complexity: int, coverage: float) -> float:
    c = float(complexity)
    return c * c * (1.0 - coverage) ** 3 + c


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_lizard_lcov_hand_calc() -> None:
    """CC 10 at 25% line coverage => CRAP 52.1875. Matches the Probe.swift case."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "sample.py"
        src.write_text("x = 1\n")
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'20,10,100,2,15,"sample.py:10",{src},"classify","classify",10,24\n',
        )
        # 8 executable lines in 10-24; 2 hit => 25%
        da = "\n".join(
            [
                f"DA:{n},{1 if n in (10, 11) else 0}"
                for n in (10, 11, 12, 13, 14, 15, 16, 17)
            ]
        )
        lcov = write(
            Path(tmp) / "coverage.info",
            f"TN:\nSF:{src}\n{da}\nend_of_record\n",
        )
        result = run_script(
            "--lizard", str(lizard), "--lcov", str(lcov), "--json", "--all"
        )
        assert result.returncode == 1, result.stderr
        payload = json.loads(result.stdout)
        fn = payload["functions"][0]
        expected = crap_of(10, 0.25)
        assert fn["complexity"] == 10
        assert abs(fn["coverage"] - 0.25) < 1e-9
        assert abs(fn["crap"] - round(expected, 2)) < 0.02
        assert fn["name"] == "classify"


def test_cobertura_matches_lcov() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "App.kt"
        src.write_text("fun x() {}\n")
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'8,5,40,1,8,"App.kt:3",{src},"tick","tick",3,10\n',
        )
        lcov = write(
            Path(tmp) / "coverage.info",
            f"TN:\nSF:{src}\nDA:3,1\nDA:4,1\nDA:5,0\nDA:6,0\nend_of_record\n",
        )
        cobertura = write(
            Path(tmp) / "coverage.xml",
            f"""<?xml version="1.0"?>
<coverage>
  <packages><package>
    <classes>
      <class filename="{src}" name="App">
        <lines>
          <line number="3" hits="1"/>
          <line number="4" hits="1"/>
          <line number="5" hits="0"/>
          <line number="6" hits="0"/>
        </lines>
      </class>
    </classes>
  </package></packages>
</coverage>
""",
        )
        a = run_script("--lizard", str(lizard), "--lcov", str(lcov), "--json", "--all")
        b = run_script(
            "--lizard", str(lizard), "--cobertura", str(cobertura), "--json", "--all"
        )
        assert a.returncode == b.returncode == 1
        fa = json.loads(a.stdout)["functions"][0]
        fb = json.loads(b.stdout)["functions"][0]
        assert fa["coverage"] == fb["coverage"] == 0.5
        assert fa["complexity"] == fb["complexity"] == 5
        assert abs(fa["crap"] - fb["crap"]) < 1e-9


def test_full_coverage_equals_complexity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "ok.ts"
        src.write_text("export function ok() {}\n")
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'12,12,80,3,12,"ok.ts:40",{src},"resolveConflicts","resolveConflicts",40,80\n',
        )
        da = "\n".join(f"DA:{n},3" for n in range(40, 48))
        lcov = write(Path(tmp) / "coverage.info", f"TN:\nSF:{src}\n{da}\nend_of_record\n")
        result = run_script(
            "--lizard",
            str(lizard),
            "--lcov",
            str(lcov),
            "--json",
            "--all",
            "--threshold",
            "6",
        )
        payload = json.loads(result.stdout)
        fn = payload["functions"][0]
        assert fn["coverage"] == 1.0
        assert fn["crap"] == 12.0
        assert result.returncode == 1  # 12 > 6


def test_summary_only_llvm_cov_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "x.swift"
        src.write_text("func f() {}\n")
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'3,1,10,0,3,"x.swift:1",{src},"f","f",1,3\n',
        )
        cov = write(Path(tmp) / "cov.json", json.dumps({"data": [{"totals": {}}]}))
        result = run_script("--lizard", str(lizard), "--coverage", str(cov))
        assert result.returncode != 0
        assert "no per-function data" in result.stderr
        assert "summary-only" in result.stderr


def test_llvm_cov_join_by_innermost_span() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "Sync.swift"
        src.write_text("func merge() {}\n")
        lint = write(
            Path(tmp) / "lint.json",
            json.dumps(
                [
                    {
                        "rule_id": "cyclomatic_complexity",
                        "file": str(src),
                        "line": 90,
                        "reason": "Function should have complexity 6 or less; currently complexity is 12",
                    }
                ]
            ),
        )
        cov = write(
            Path(tmp) / "cov.json",
            json.dumps(
                {
                    "data": [
                        {
                            "functions": [
                                {
                                    "name": "merge",
                                    "count": 0,
                                    "filenames": [str(src)],
                                    "regions": [
                                        [80, 1, 120, 2, 0, 0, 0, 0],
                                        [90, 1, 100, 2, 0, 0, 0, 0],
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ),
        )
        result = run_script("--lint", str(lint), "--coverage", str(cov), "--json", "--all")
        assert result.returncode == 1, result.stderr
        fn = json.loads(result.stdout)["functions"][0]
        assert fn["complexity"] == 12
        assert fn["coverage"] == 0.0
        assert fn["crap"] == 156.0
        assert fn["name"] == "merge"


def test_unmatched_file_scores_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "missing.py"
        other = Path(tmp) / "other.py"
        src.write_text("def f():\n    pass\n")
        other.write_text("def g():\n    pass\n")
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'5,3,20,1,5,"missing.py:1",{src},"f","f",1,5\n',
        )
        lcov = write(
            Path(tmp) / "coverage.info",
            f"TN:\nSF:{other}\nDA:1,1\nend_of_record\n",
        )
        result = run_script(
            "--lizard", str(lizard), "--lcov", str(lcov), "--json", "--all"
        )
        fn = json.loads(result.stdout)["functions"][0]
        assert fn["matched_coverage"] is False
        assert fn["coverage"] == 0.0
        assert "not in the coverage report" in fn["warnings"][0]


def test_basename_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "mod.py"
        src.write_text("def f():\n    return 1\n")
        # lizard path is the real file; lcov path is a copy-looking basename-only match
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'4,2,15,0,4,"mod.py:1",{src},"f","f",1,4\n',
        )
        lcov = write(
            Path(tmp) / "coverage.info",
            "TN:\nSF:/unrelated/mod.py\nDA:1,1\nDA:2,1\nend_of_record\n",
        )
        result = run_script(
            "--lizard", str(lizard), "--lcov", str(lcov), "--json", "--all"
        )
        fn = json.loads(result.stdout)["functions"][0]
        assert fn["matched_coverage"] is True
        assert fn["coverage"] == 1.0
        assert any("filename" in w for w in fn["warnings"])


def test_xccov_hits_drops_non_executable() -> None:
    """xccov marks every line, executable or not. Only executable ones are hits."""
    payload = {
        "/tmp/Sample.swift": [
            {"isExecutable": False, "line": 1},
            {"isExecutable": True, "line": 2, "executionCount": 7},
            {"isExecutable": True, "line": 3, "executionCount": 0},
            {"isExecutable": True, "line": 4},
            {"isExecutable": False, "line": 5},
        ]
    }
    hits = crap.xccov_hits(payload)
    key = crap.normalize("/tmp/Sample.swift")
    assert list(hits) == [key], hits
    # Line 4 is executable with no executionCount key -> 0 hits, not dropped.
    assert hits[key] == {2: 7, 3: 0, 4: 0}, hits[key]


def test_xccov_hits_ignores_malformed() -> None:
    assert crap.xccov_hits(["not", "a", "dict"]) == {}
    assert crap.xccov_hits({"/tmp/a.swift": "not a list"}) == {}
    # A file whose every line is non-executable contributes nothing.
    assert crap.xccov_hits({"/tmp/a.swift": [{"isExecutable": False, "line": 1}]}) == {}


def test_xccov_argv_archive_flag_depends_on_bundle_type() -> None:
    """An .xcresult needs --archive; an .xccovarchive rejects it."""
    result = crap.xccov_argv("Build.xcresult", ["--file-list"])
    assert result == ["xcrun", "xccov", "view", "--archive", "--file-list", "Build.xcresult"]
    archive = crap.xccov_argv("Build.xccovarchive", ["--file-list"])
    assert archive == ["xcrun", "xccov", "view", "--file-list", "Build.xccovarchive"]
    # A trailing slash must not defeat the suffix check.
    assert "--archive" not in crap.xccov_argv("Build.xccovarchive/", ["--file-list"])


def test_xccov_scores_like_equivalent_lcov() -> None:
    """xccov line hits and the same hits as lcov must produce identical CRAP."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "Sample.swift"
        src.write_text("// swift\n")
        lizard = write(
            Path(tmp) / "lizard.csv",
            f'20,10,100,2,15,"Sample.swift:10",{src},"classify","classify",10,17\n',
        )
        # 8 executable lines, 2 hit => 25% => CRAP 52.1875 for complexity 10.
        hits = {n: (1 if n in (10, 11) else 0) for n in range(10, 18)}
        lcov = write(
            Path(tmp) / "coverage.info",
            "TN:\nSF:%s\n%s\nend_of_record\n"
            % (src, "\n".join(f"DA:{n},{h}" for n, h in hits.items())),
        )
        from_lcov = run_script("--lizard", str(lizard), "--lcov", str(lcov), "--json", "--all")
        assert from_lcov.returncode == 1, from_lcov.stderr
        expected = json.loads(from_lcov.stdout)["functions"][0]

        payload = {
            str(src): [
                {"isExecutable": True, "line": n, "executionCount": h}
                for n, h in hits.items()
            ]
        }
        units = crap.parse_lizard(str(lizard))
        rows = crap.build_rows_lines(units, crap.xccov_hits(payload))
        assert len(rows) == 1, rows
        assert abs(rows[0].crap - expected["crap"]) < 0.01, (rows[0].crap, expected["crap"])
        assert abs(rows[0].crap - crap_of(10, 0.25)) < 1e-9, rows[0].crap


def test_xccov_missing_bundle_exits() -> None:
    result = run_script("--lizard", "/nope.csv", "--xcresult", "/nope.xcresult")
    assert result.returncode != 0
    assert "no such file" in (result.stdout + result.stderr).lower()


def test_zero_width_lint_unit_warns_about_lizard() -> None:
    """A --lint unit against line coverage says what to do instead."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "Sample.swift"
        src.write_text("// swift\n")
        lint = write(
            Path(tmp) / "lint.json",
            json.dumps(
                [
                    {
                        "rule_id": "cyclomatic_complexity",
                        "file": str(src),
                        "line": 42,
                        "reason": "Function should have complexity 10 or less; "
                        "currently complexity is 19",
                    }
                ]
            ),
        )
        # Executable lines exist, but none on line 42 itself.
        lcov = write(
            Path(tmp) / "coverage.info",
            f"TN:\nSF:{src}\nDA:50,1\nDA:51,0\nend_of_record\n",
        )
        result = run_script("--lint", str(lint), "--lcov", str(lcov), "--json", "--all")
        fn = json.loads(result.stdout)["functions"][0]
        assert fn["coverage"] == 0.0
        assert any("--lizard" in w for w in fn["warnings"]), fn["warnings"]


def main() -> int:
    tests = [
        test_lizard_lcov_hand_calc,
        test_cobertura_matches_lcov,
        test_full_coverage_equals_complexity,
        test_summary_only_llvm_cov_rejected,
        test_llvm_cov_join_by_innermost_span,
        test_unmatched_file_scores_zero,
        test_basename_fallback,
        test_xccov_hits_drops_non_executable,
        test_xccov_hits_ignores_malformed,
        test_xccov_argv_archive_flag_depends_on_bundle_type,
        test_xccov_scores_like_equivalent_lcov,
        test_xccov_missing_bundle_exits,
        test_zero_width_lint_unit_warns_about_lizard,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"ok   {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
