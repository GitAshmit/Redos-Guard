import itertools
import random
import re
import sys

import pytest

sys.setrecursionlimit(8000)

from redos import parse
from redos.dfa import alphabet_classes, build_dfa, dfa_dot, dfa_match, minimize
from redos.nfa import build_nfa, remove_epsilon

PATTERNS = [
    r"(a+)+", r"(a|b)*c", r"a*b*", r"(ab|a)(bc|c)?", r"[a-c]+x?", r"(a|ab)*b",
    r"a{2,3}b?", r"(?:a|b){3}", r"[^a]b*", r".a.", r"(a*)*b", r"a?a?a?aaa", r"(a|b)*abb",
]


def compile_dfa(pattern):
    nfa = build_nfa(parse(pattern))
    efn = remove_epsilon(nfa)
    classes = alphabet_classes(m for _, m, _ in nfa.edges)
    dfa = build_dfa(efn, classes)
    return dfa, minimize(dfa)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_dfa_and_min_dfa_agree_with_python_re(pattern):
    dfa, mdfa = compile_dfa(pattern)
    assert mdfa.n <= dfa.n
    rx = re.compile(pattern)
    rng = random.Random(7)
    words = ["".join(w) for n in range(0, 6) for w in itertools.product("abcx", repeat=n)]
    words += ["".join(rng.choice("abcxé\t") for _ in range(rng.randint(5, 14))) for _ in range(150)]
    for w in words:
        expected = rx.fullmatch(w) is not None
        assert dfa_match(dfa, w)[0] == expected, (pattern, w)
        assert dfa_match(mdfa, w)[0] == expected, (pattern, w)


def test_classic_min_dfa_has_four_live_states():
    # (a|b)*abb is the textbook example: minimal DFA has 4 states (plus the dead state here)
    _, mdfa = compile_dfa(r"(a|b)*abb")
    assert mdfa.live_states == 4


def test_minimization_merges_equivalent_states():
    dfa, mdfa = compile_dfa(r"(a|a)*(b|b)")
    assert mdfa.live_states == 2
    assert dfa.n > mdfa.n


def test_alphabet_classes_partition():
    from redos import charset as cs
    classes = alphabet_classes([cs.DIGIT, cs.LOWER, cs.WORD])
    assert sum(bin(c).count("1") for c in classes) == cs.SIZE
    assert all(a & b == 0 for a, b in itertools.combinations(classes, 2))


def test_dfa_is_linear_on_attack_string():
    _, mdfa = compile_dfa(r"(a+)+")
    ok, steps = dfa_match(mdfa, "a" * 5000 + "!")
    assert ok is False and steps <= 5001


def test_dot_output():
    _, mdfa = compile_dfa(r"ab*")
    dot = dfa_dot(mdfa)
    assert dot.startswith("digraph DFA") and "doublecircle" in dot
