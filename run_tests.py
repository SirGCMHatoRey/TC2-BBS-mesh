#!/usr/bin/env python3
"""Run the whole suite. No test framework required.

Each file runs in its own process. That is not incidental: the tests replace
the one remaining piece of module-level state — the conversation states in
utils — and a shared interpreter would let one file's substitute leak into the
next. See docs/adr/0004: the database connection and the settings cache are
already passed rather than global; once the conversation state is too, this
isolation stops being necessary.

    python run_tests.py              # everything
    python run_tests.py mail board   # only files whose name contains these
"""

import pathlib
import subprocess
import sys

TESTS = pathlib.Path(__file__).parent / "tests"


def main(patterns):
    files = sorted(TESTS.glob("test_*.py"))
    if patterns:
        files = [f for f in files if any(p in f.name for p in patterns)]
    if not files:
        print("no test files matched")
        return 1

    width = max(len(f.stem) for f in files)
    failed = []
    total = 0

    for path in files:
        result = subprocess.run([sys.executable, str(path)],
                                capture_output=True, text=True)
        tail = result.stdout.strip().splitlines()
        summary = tail[-1] if tail else "(no output)"
        ok = result.returncode == 0 and "FAIL" not in result.stdout

        for line in tail:
            if line.startswith("ok "):
                total += 1

        print(f"{path.stem:<{width}}  {summary}")
        if not ok:
            failed.append(path.stem)
            for line in result.stdout.splitlines():
                if line.startswith("FAIL"):
                    print(f"    {line}")
            if result.stderr.strip():
                print(f"    stderr: {result.stderr.strip().splitlines()[-1]}")

    print()
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(f"{total} tests passed across {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
