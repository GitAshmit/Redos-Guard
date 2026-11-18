"""Glue: regex string -> verdict, attack string, benchmark and Graphviz output."""
from functools import lru_cache
from time import perf_counter

from . import charset as cs
from .ambiguity import find_eda
from .dfa import DFATooLarge, alphabet_classes, build_dfa, dfa_dot, dfa_match, minimize
from .matchers import backtrack_match
from .nfa import build_nfa, nfa_dot, nfa_match, remove_epsilon
from .parser import parse

ATTACK_REPEATS = 30  # pump repeats in the attack string shown to the user
_SUFFIX_CANDIDATES = ["!"] + [chr(o) for o in range(33, 127) if chr(o) != "!"] + [" "]


@lru_cache(maxsize=64)
def compile_regex(pattern):
    """Parse and build everything once: (ast, nfa, efn, dfa, min_dfa, dfa_error)."""
    ast = parse(pattern)
    nfa = build_nfa(ast)
    efn = remove_epsilon(nfa)
    classes = alphabet_classes(m for _, m, _ in nfa.edges)
    try:
        dfa = build_dfa(efn, classes)
        return ast, nfa, efn, dfa, minimize(dfa), None
    except DFATooLarge as e:
        return ast, nfa, efn, None, None, str(e)


def _pick_suffix(efn, prefix, pump):
    """A character that makes prefix + pump^k + c rejected, so the engine must give up."""
    base = prefix + pump * 8
    for c in _SUFFIX_CANDIDATES:
        if not nfa_match(efn, base + c)[0]:
            return c
    return None


def _benchmark(ast, efn, mdfa, prefix, pump, suffix, max_steps, max_pump):
    rows = []
    for k in range(2, max_pump + 1, 2):
        s = prefix + pump * k + suffix
        t0 = perf_counter()
        matched, steps, capped = backtrack_match(ast, s, max_steps)
        t1 = perf_counter()
        nmatched, nsteps = nfa_match(efn, s)
        t2 = perf_counter()
        dmatched, dsteps = dfa_match(mdfa, s) if mdfa else (None, None)
        t3 = perf_counter()
        rows.append({
            "pump_repeats": k, "length": len(s),
            "backtrack_steps": steps, "backtrack_ms": round((t1 - t0) * 1000, 3),
            "backtrack_capped": capped, "backtrack_matched": matched,
            "nfa_steps": nsteps, "nfa_ms": round((t2 - t1) * 1000, 3), "nfa_matched": nmatched,
            "dfa_steps": dsteps, "dfa_ms": round((t3 - t2) * 1000, 3), "dfa_matched": dmatched,
        })
        if capped:
            break
    return rows


def _growth_confirmed(rows):
    if not rows:
        return False
    if rows[-1]["backtrack_capped"]:
        return True
    if len(rows) >= 2:
        a, b = rows[-2]["backtrack_steps"], rows[-1]["backtrack_steps"]
        return b >= 10_000 and b >= 1.5 * a
    return False


def analyze(pattern, max_steps=1_000_000, max_pump=40):
    """Analyse `pattern`. Raises RegexSyntaxError for unsupported / invalid syntax."""
    ast, nfa, efn, dfa, mdfa, dfa_error = compile_regex(pattern)
    eda = find_eda(efn)

    result = {
        "regex": pattern,
        "nfa": {"thompson_states": nfa.n, "states": efn.n, "edges": efn.edge_count,
                "accepting": sorted(efn.finals)},
        "eda": None, "attack": None, "benchmark": [],
        "dfa": ({"states": dfa.live_states, "min_states": mdfa.live_states,
                 "classes": [cs.label(c) for c in dfa.classes],
                 "accepting": len(mdfa.accept), "dot": dfa_dot(mdfa)}
                if dfa else {"error": dfa_error}),
    }

    if eda is None:
        result.update(
            verdict="safe",
            reason=("No exponential ambiguity in the NFA, so a backtracking engine cannot blow up "
                    "exponentially. Polynomial slowdowns (for example a*a*) are not checked yet."),
        )
        result["dot"] = nfa_dot(efn)
        return result

    result["eda"] = {"state": eda.state, "prefix": eda.prefix, "pump": eda.pump}
    result["dot"] = nfa_dot(efn, highlight=eda.state)
    suffix = _pick_suffix(efn, eda.prefix, eda.pump)
    if suffix is None:
        result.update(
            verdict="suspicious",
            reason=("The NFA is exponentially ambiguous, but no failing suffix was found, so the "
                    "engine would accept (or stop) quickly on the inputs tried."),
        )
        return result

    rows = _benchmark(ast, efn, mdfa, eda.prefix, eda.pump, suffix, max_steps, max_pump)
    result["benchmark"] = rows
    result["attack"] = {
        "prefix": eda.prefix, "pump": eda.pump, "suffix": suffix, "repeats": ATTACK_REPEATS,
        "string": eda.prefix + eda.pump * ATTACK_REPEATS + suffix,
    }
    if _growth_confirmed(rows):
        result.update(
            verdict="vulnerable",
            reason=(f"The NFA has two different paths from state q{eda.state} back to itself on "
                    f"{eda.pump!r}. Each extra repeat multiplies the backtracking work, and the "
                    "measured step count confirms the growth."),
        )
    else:
        result.update(
            verdict="suspicious",
            reason=("Exponential ambiguity found, but the measured growth stayed small within the "
                    "tested lengths."),
        )
    return result
