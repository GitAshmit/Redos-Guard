"""NFA -> DFA by subset construction, Moore minimization, and a linear-time matcher.

The alphabet is split into equivalence classes (characters that every edge treats the same),
so the DFA table has one column per class instead of one per character. One extra column
stands for "character outside the supported ASCII range", which always leads to the dead state.
"""
from . import charset as cs

MAX_DFA_STATES = 1500


class DFATooLarge(Exception):
    pass


def alphabet_classes(masks):
    """Partition the alphabet into classes that no mask in `masks` can tell apart."""
    classes = [cs.FULL]
    for m in set(masks):
        refined = []
        for c in classes:
            inside, outside = c & m, c & ~m
            if inside:
                refined.append(inside)
            if outside:
                refined.append(outside)
        classes = refined
    return sorted(classes, key=lambda c: c & -c)


class DFA:
    """Complete DFA. State 0 is the start state; column len(classes) is 'outside the alphabet'."""

    def __init__(self, classes, trans, accept):
        self.classes, self.trans, self.accept = classes, trans, accept
        self.n = len(trans)
        k = len(classes)
        self.cmap = [k] * 128
        for ci, mask in enumerate(classes):
            for o in range(cs.LO, cs.HI + 1):
                if mask >> (o - cs.LO) & 1:
                    self.cmap[o] = ci
        # dead state: non-accepting and every transition loops back to itself
        self.dead = next(
            (s for s in range(self.n) if s not in accept and all(t == s for t in trans[s])), None
        )

    @property
    def live_states(self):
        return self.n - (1 if self.dead is not None else 0)


def build_dfa(efn, classes, max_states=MAX_DFA_STATES):
    k = len(classes)
    start = frozenset([efn.start])
    ids, order, trans = {start: 0}, [start], []

    def state_id(subset):
        if subset not in ids:
            if len(order) >= max_states:
                raise DFATooLarge(f"DFA has more than {max_states} states")
            ids[subset] = len(order)
            order.append(subset)
        return ids[subset]

    i = 0
    while i < len(order):
        subset = order[i]
        row = []
        for cmask in classes:
            row.append(state_id(frozenset(
                r for q in subset for (m, r) in efn.out[q] if m & cmask
            )))
        row.append(state_id(frozenset()))  # outside the alphabet
        trans.append(row)
        i += 1
    accept = {ids[s] for s in order if s & efn.finals}
    return DFA(classes, trans, accept)


def minimize(dfa):
    """Moore partition refinement. Equivalent states end up in the same block."""
    n = dfa.n
    block = [1 if s in dfa.accept else 0 for s in range(n)]
    count = len(set(block))
    while True:
        sigs, new = {}, []
        for s in range(n):
            sig = (block[s],) + tuple(block[t] for t in dfa.trans[s])
            new.append(sigs.setdefault(sig, len(sigs)))
        block = new
        if len(sigs) == count:
            break
        count = len(sigs)
    # block ids follow first appearance, so the start state's block is 0
    rep = {}
    for s in range(n):
        rep.setdefault(block[s], s)
    trans = [[block[t] for t in dfa.trans[rep[b]]] for b in range(count)]
    accept = {block[s] for s in dfa.accept}
    return DFA(dfa.classes, trans, accept)


def dfa_match(dfa, s):
    """Full match in one pass. Returns (matched, steps); steps = characters consumed."""
    st, k, steps = 0, len(dfa.classes), 0
    for ch in s:
        o = ord(ch)
        st = dfa.trans[st][dfa.cmap[o] if o < 128 else k]
        steps += 1
        if st == dfa.dead:
            break
    return st in dfa.accept, steps


def dfa_dot(dfa):
    lines = ["digraph DFA {", "  rankdir=LR;", '  node [shape=circle, fontname="Helvetica"];',
             '  edge [fontname="Helvetica"];', "  __start [shape=point];", "  __start -> s0;"]
    for q in range(dfa.n):
        if q == dfa.dead:
            continue
        lines.append(f"  s{q} [shape=doublecircle];" if q in dfa.accept else f"  s{q};")
    merged = {}
    for q in range(dfa.n):
        if q == dfa.dead:
            continue
        for ci, r in enumerate(dfa.trans[q][:-1]):
            if r != dfa.dead:
                merged.setdefault((q, r), []).append(cs.label(dfa.classes[ci]))
    for (q, r), labels in sorted(merged.items()):
        text = ", ".join(labels).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  s{q} -> s{r} [label="{text}"];')
    lines.append("}")
    return "\n".join(lines)
