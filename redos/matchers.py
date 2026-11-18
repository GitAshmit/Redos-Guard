"""Backtracking matcher over the AST (mimics a greedy engine such as Python's re).

It exists to *measure* the blow-up: every character comparison is one step, and the
run is aborted once `max_steps` is reached.
"""
from . import charset as cs
from .parser import Alt, Cat, CharSet, Empty, Opt, Plus


class _StepLimit(Exception):
    pass


def backtrack_match(ast, s, max_steps=1_000_000):
    """Full match of `s`. Returns (matched, steps, capped); matched is None when capped."""
    n = len(s)
    bits = [1 << (ord(c) - cs.LO) if cs.LO <= ord(c) <= cs.HI else 0 for c in s]
    steps = 0

    def tick():
        nonlocal steps
        steps += 1
        if steps > max_steps:
            raise _StepLimit

    def star(child, i, k):
        # greedy: try one more iteration first (it must consume input), then leave the loop
        if m(child, i, lambda j: j > i and star(child, j, k)):
            return True
        return k(i)

    def m(node, i, k):
        if isinstance(node, CharSet):
            tick()
            return i < n and bool(node.mask & bits[i]) and k(i + 1)
        if isinstance(node, Empty):
            return k(i)
        if isinstance(node, Cat):
            parts = node.parts

            def go(idx, pos):
                if idx == len(parts):
                    return k(pos)
                return m(parts[idx], pos, lambda j: go(idx + 1, j))

            return go(0, i)
        if isinstance(node, Alt):
            return any(m(opt, i, k) for opt in node.options)
        if isinstance(node, Plus):
            return m(node.child, i, lambda j: star(node.child, j, k))
        if isinstance(node, Opt):
            return m(node.child, i, k) or k(i)
        return star(node.child, i, k)  # Star

    try:
        return bool(m(ast, 0, lambda j: j == n)), steps, False
    except (_StepLimit, RecursionError):
        return None, steps, True
