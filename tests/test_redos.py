import itertools
import random
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.setrecursionlimit(8000)

from redos import RegexSyntaxError, analyze, parse
from redos.api import app
from redos.matchers import backtrack_match
from redos.nfa import build_nfa, nfa_match, remove_epsilon

VULNERABLE = [
    r"(a+)+",
    r"(a*)*",
    r"(a|a)*",
    r"(a|aa)+",
    r"(a|b|ab)*",
    r"([a-z]+)*",
    r"^(([a-z])+.)+[A-Z]([a-z])+$",  # classic OWASP example
    r"(\w+\s?)*",
    r"(x+x+)+y",
    r"(a{2,3})+",
]

SAFE = [
    r"a*b*",
    r"(ab)*",
    r"[a-z]+@[a-z]+\.com",
    r"\d+(\.\d+)?",
    r"a+b+",
    r"(a|b)*c",
    r"^[a-z0-9_.-]+$",
    r"(foo|bar|baz)+",
    r"[^@\s]+@[^@\s]+",
]

MATCH_PATTERNS = [
    r"(a+)+", r"(a|b)*c", r"a*b*", r"(ab|a)(bc|c)?", r"[a-c]+x?", r"(a|ab)*b",
    r"a{2,3}b?", r"(?:a|b){3}", r"[^a]b*", r".a.", r"(a*)*b", r"a?a?a?aaa",
]


@pytest.mark.parametrize("pattern", VULNERABLE)
def test_vulnerable_detected_and_confirmed(pattern):
    r = analyze(pattern, max_steps=300_000)
    assert r["verdict"] == "vulnerable", r["reason"]
    assert r["attack"] and r["benchmark"]
    last = r["benchmark"][-1]
    # the attack string really is rejected, and the linear simulation stays tiny
    assert last["nfa_matched"] is False
    assert last["nfa_steps"] < 5 * last["length"] * r["nfa"]["states"]


@pytest.mark.parametrize("pattern", SAFE)
def test_safe_not_flagged(pattern):
    r = analyze(pattern)
    assert r["verdict"] == "safe"
    assert r["eda"] is None


def test_known_attack_string_shape():
    r = analyze(r"(a+)+")
    assert set(r["attack"]["pump"]) == {"a"} and r["attack"]["suffix"] == "!"


def test_growth_is_exponential_for_classic_case():
    rows = analyze(r"(a+)+", max_steps=2_000_000)["benchmark"]
    uncapped = [x["backtrack_steps"] for x in rows if not x["backtrack_capped"]]
    assert len(uncapped) >= 3
    assert all(b > 2 * a for a, b in zip(uncapped, uncapped[1:]))


@pytest.mark.parametrize("pattern", MATCH_PATTERNS)
def test_matchers_agree_with_python_re(pattern):
    ast = parse(pattern)
    efn = remove_epsilon(build_nfa(ast))
    rx = re.compile(pattern, re.DOTALL if False else 0)
    rng = random.Random(1)
    words = ["".join(w) for n in range(0, 5) for w in itertools.product("abcx", repeat=n)]
    words += ["".join(rng.choice("abcx") for _ in range(rng.randint(5, 12))) for _ in range(100)]
    for w in words:
        expected = rx.fullmatch(w) is not None
        got_bt, _, capped = backtrack_match(ast, w, 5_000_000)
        assert not capped
        assert got_bt == expected, (pattern, w)
        assert nfa_match(efn, w)[0] == expected, (pattern, w)


@pytest.mark.parametrize("pattern", ["(", "a)", "a**", "[a", "\\1", "(?=a)", "*a", "a{2", "a{3,1}",
                                     "a{99}", "a^b", "\\", "a++", "café"])
def test_syntax_errors(pattern):
    with pytest.raises(RegexSyntaxError):
        parse(pattern)


def test_anchors_stripped():
    assert nfa_match(remove_epsilon(build_nfa(parse("^ab$"))), "ab")[0]
    assert not nfa_match(remove_epsilon(build_nfa(parse("^ab$"))), "abb")[0]


def test_too_large_regex_rejected():
    with pytest.raises(RegexSyntaxError):
        analyze("(((a{50}){50}){50})")


client = TestClient(app)


def test_api_ok():
    r = client.post("/analyze", json={"regex": "(a+)+"})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "vulnerable"
    assert body["dot"].startswith("digraph NFA")
    assert body["attack"]["string"].endswith("!")


def test_api_syntax_error():
    r = client.post("/analyze", json={"regex": "(a"})
    assert r.status_code == 422
    assert r.json()["detail"]["error"]


def test_api_rejects_empty_and_health():
    assert client.post("/analyze", json={"regex": ""}).status_code == 422
    assert client.get("/health").json() == {"status": "ok"}
