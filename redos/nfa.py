"""Thompson NFA construction, epsilon removal, simulation and Graphviz export."""
from . import charset as cs
from .parser import Alt, Cat, CharSet, Empty, Opt, Plus, RegexSyntaxError, Star

MAX_STATES = 1000


class NFA:
    """Thompson NFA with epsilon moves. Single start (0 is not guaranteed) and single accept."""

    def __init__(self):
        self.eps = []    # eps[s] = list of states reachable by an epsilon move
        self.edges = []  # (src, mask, dst)
        self.start = self.accept = 0

    @property
    def n(self):
        return len(self.eps)


def build_nfa(ast, max_states=MAX_STATES):
    nfa = NFA()

    def new():
        if len(nfa.eps) >= max_states:
            raise RegexSyntaxError(f"regex is too large (more than {max_states} NFA states)")
        nfa.eps.append([])
        return len(nfa.eps) - 1

    def frag(node):
        if isinstance(node, CharSet):
            s, e = new(), new()
            nfa.edges.append((s, node.mask, e))
            return s, e
        if isinstance(node, Empty):
            s, e = new(), new()
            nfa.eps[s].append(e)
            return s, e
        if isinstance(node, Cat):
            s, e = frag(node.parts[0])
            for part in node.parts[1:]:
                a, b = frag(part)
                nfa.eps[e].append(a)
                e = b
            return s, e
        if isinstance(node, Alt):
            s, e = new(), new()
            for opt in node.options:
                a, b = frag(opt)
                nfa.eps[s].append(a)
                nfa.eps[b].append(e)
            return s, e
        # Star / Plus / Opt (Plus and Opt subclass Star, so test them first)
        a, b = frag(node.child)
        s, e = new(), new()
        nfa.eps[s].append(a)
        if not isinstance(node, Plus):
            nfa.eps[s].append(e)           # skip the body (star, opt)
        if not isinstance(node, Opt):
            nfa.eps[b].extend([a, e])      # loop or leave (star, plus)
        else:
            nfa.eps[b].append(e)
        return s, e

    nfa.start, nfa.accept = frag(ast)
    return nfa


class EFNFA:
    """Epsilon-free, trimmed NFA. State 0 is the start state.

    out[q] is a list of (charset_mask, dst). Parallel edges are kept distinct on purpose:
    two different edges q->r are two different paths, which is exactly what ambiguity counts.
    """

    def __init__(self, n, finals, out):
        self.n, self.start, self.finals, self.out = n, 0, finals, out

    @property
    def edge_count(self):
        return sum(len(o) for o in self.out)


def remove_epsilon(nfa):
    n = nfa.n
    by_src = [[] for _ in range(n)]
    for s, m, d in nfa.edges:
        by_src[s].append((m, d))
    # Epsilon removal that keeps route multiplicity. A backtracking engine treats two different
    # epsilon routes to the same character edge as two different attempts, so each route
    # becomes its own parallel edge. (a+)+ is the standard example: after reading 'a' the engine
    # can loop in the inner or the outer plus, and both end on the same edge. Counting routes
    # per target is capped at 2, since "two or more" is all the ambiguity test needs.
    out, fin = [], set()
    for q in range(n):
        entered = {}
        on_path = set()
        edges = []

        def visit(p):
            entered[p] = entered.get(p, 0) + 1
            on_path.add(p)
            edges.extend(by_src[p])
            for w in nfa.eps[p]:
                if w not in on_path and entered.get(w, 0) < 2:
                    visit(w)
            on_path.discard(p)

        visit(q)
        if nfa.accept in entered:
            fin.add(q)
        out.append(edges)

    # keep only states that are reachable from the start and can still reach an accepting state
    fwd, stack = {nfa.start}, [nfa.start]
    while stack:
        v = stack.pop()
        for _, d in out[v]:
            if d not in fwd:
                fwd.add(d)
                stack.append(d)
    rev = [[] for _ in range(n)]
    for q in range(n):
        for _, d in out[q]:
            rev[d].append(q)
    bwd, stack = set(fin), list(fin)
    while stack:
        v = stack.pop()
        for p in rev[v]:
            if p not in bwd:
                bwd.add(p)
                stack.append(p)
    useful = fwd & bwd
    if nfa.start not in useful:  # empty language
        return EFNFA(1, set(), [[]])
    ids = {nfa.start: 0}
    for q in sorted(useful - {nfa.start}):
        ids[q] = len(ids)
    new_out = [[] for _ in ids]
    for q in useful:
        for m, d in out[q]:
            if d in useful:
                new_out[ids[q]].append((m, ids[d]))
    return EFNFA(len(ids), {ids[q] for q in useful if q in fin}, new_out)


def nfa_match(efn, s):
    """Linear-time simulation (set of current states). Returns (matched, work_steps)."""
    cur, steps = {efn.start}, 0
    for ch in s:
        o = ord(ch)
        b = 1 << (o - cs.LO) if cs.LO <= o <= cs.HI else 0
        nxt = set()
        for q in cur:
            steps += 1
            for m, r in efn.out[q]:
                if m & b:
                    nxt.add(r)
        cur = nxt
        if not cur:
            break
    return bool(cur & efn.finals), steps


def nfa_dot(efn, highlight=None):
    """Graphviz DOT source for the epsilon-free NFA; `highlight` is a state drawn in red."""
    lines = ["digraph NFA {", "  rankdir=LR;", '  node [shape=circle, fontname="Helvetica"];',
             '  edge [fontname="Helvetica"];', '  __start [shape=point];', "  __start -> q0;"]
    for q in range(efn.n):
        attrs = []
        if q in efn.finals:
            attrs.append("shape=doublecircle")
        if q == highlight:
            attrs.append('color=red, fontcolor=red')
        lines.append(f"  q{q} [{', '.join(attrs)}];" if attrs else f"  q{q};")
    merged = {}
    for q in range(efn.n):
        for m, r in efn.out[q]:
            merged.setdefault((q, r), []).append(cs.label(m))
    for (q, r), labels in sorted(merged.items()):
        counts = {}
        for lab in labels:
            counts[lab] = counts.get(lab, 0) + 1
        text = ", ".join(f"{lab} x{k}" if k > 1 else lab for lab, k in counts.items())
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  q{q} -> q{r} [label="{text}"];')
    lines.append("}")
    return "\n".join(lines)
