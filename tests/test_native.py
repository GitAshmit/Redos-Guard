"""Compile the ESP32 matching core with g++ and check it against Python's re module."""
import itertools
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from redos.export import to_c_header

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="g++ not installed")

PATTERNS = [r"(a+)+", r"(a|b)*abb", r"[a-c]+x?", r"(ab|a)(bc|c)?", r"a{2,3}b?", r"[^a]b*",
            r"(a*)*b", r"\d+(\.\d+)?", r"(a|aa)+"]


def build(tmp_path, pattern):
    # copy the core next to the generated tables: a quoted #include looks in the including
    # file's own folder first, and esp32/redos_demo has its own default redos_tables.h
    (tmp_path / "redos_tables.h").write_text(to_c_header(pattern))
    shutil.copy(ROOT / "esp32" / "redos_demo" / "redos_core.h", tmp_path / "redos_core.h")
    exe = tmp_path / "harness"
    subprocess.run(
        ["g++", "-std=c++17", "-O1", "-Wall", "-I", str(tmp_path),
         str(ROOT / "tests" / "native_harness.cpp"), "-o", str(exe)],
        check=True, capture_output=True, text=True,
    )
    return exe


@pytest.mark.parametrize("pattern", PATTERNS)
def test_core_matches_python_re(tmp_path, pattern):
    exe = build(tmp_path, pattern)
    rng = random.Random(3)
    words = ["".join(w) for n in range(0, 5) for w in itertools.product("abcx1.", repeat=n)]
    words += ["".join(rng.choice("abcx1.") for _ in range(rng.randint(5, 12))) for _ in range(80)]
    out = subprocess.run([str(exe)], input="\n".join(words) + "\n", capture_output=True, text=True,
                         check=True).stdout.splitlines()
    assert len(out) == len(words)
    rx = re.compile(pattern)
    for w, line in zip(words, out):
        bt, dfa, _, capped = map(int, line.split())
        expected = rx.fullmatch(w) is not None
        assert not capped, (pattern, w)
        assert bool(bt) == expected, ("backtracker", pattern, w)
        assert bool(dfa) == expected, ("dfa", pattern, w)


def test_core_backtracker_blows_up_dfa_does_not(tmp_path):
    exe = build(tmp_path, r"(a+)+")
    words = ["a" * k + "!" for k in (10, 14, 18)]
    out = subprocess.run([str(exe)], input="\n".join(words) + "\n", capture_output=True, text=True,
                         check=True).stdout.splitlines()
    steps = [int(line.split()[2]) for line in out]
    assert steps[1] > 8 * steps[0] and steps[2] > 8 * steps[1]
    assert all(line.split()[1] == "0" for line in out)  # DFA rejects, instantly
