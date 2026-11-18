"""Exponential ambiguity (EDA) detection on an epsilon-free, trimmed NFA with parallel edges.

A regex can make a backtracking engine take exponential time when its NFA has a state q
and a word w with two *different* paths q --w--> q (the EDA condition of Weber and Seidl).
Different means different edge sequences, so parallel edges count (see remove_epsilon).

In the product automaton A x A (pairs of states reading the same character) an edge is
"diverging" when the two components use different NFA edges. Two different paths q -> q on
the same word exist exactly when the diagonal pair (q, q) lies in a strongly connected
component that contains a diverging edge: leave (q, q) on a diverging edge, come back.
"""
from collections import deque
from dataclasses import dataclass

from . import charset as cs


@dataclass
class EDA:
    state: int    # NFA state q where the two paths split and rejoin
    prefix: str   # shortest word from the start state to q
    pump: str     # word w with two different paths q -> q


def _shortest_word(efn, goal):
    """Shortest word from the start state to `goal` (BFS)."""
    prev = {efn.start: None}
    dq = deque([efn.start])
    while dq:
        v = dq.popleft()
        if v == goal:
            break
        for mask, r in efn.out[v]:
            if r not in prev:
                prev[r] = (v, cs.pick(mask))
                dq.append(r)
    chars, v = [], goal
    while prev[v] is not None:
        v, c = prev[v]
        chars.append(c)
    return "".join(reversed(chars))


def find_eda(efn):
    """Return an EDA witness, or None if the NFA has no exponential ambiguity."""
    n = efn.n
    cache = {}

    def adj(node):
        """Product edges from node: list of (target, intersection mask, is_diverging)."""
        if node not in cache:
            p, q = divmod(node, n)
            res = []
            for i, (m1, r1) in enumerate(efn.out[p]):
                for j, (m2, r2) in enumerate(efn.out[q]):
                    inter = m1 & m2
                    if inter:
                        res.append((r1 * n + r2, inter, not (p == q and i == j)))
            cache[node] = res
        return cache[node]

    # iterative Tarjan SCC, started from every diagonal pair (an SCC containing a diagonal
    # pair is reachable from it, so these roots are enough)
    index, low, comp = {}, {}, {}
    stack, on_stack = [], set()
    counter = ncomp = 0
    for q in range(n):
        root = q * n + q
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(adj(root)))]
        while work:
            v, it = work[-1]
            advanced = False
            for w, _, _ in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(adj(w))))
                    advanced = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp[w] = ncomp
                    if w == v:
                        break
                ncomp += 1

    # SCCs that contain a diverging edge between two of their own nodes
    diverging = {}  # node -> (target, char) of one diverging edge inside its SCC
    for v, c in comp.items():
        for w, inter, div in adj(v):
            if div and comp.get(w) == c:
                diverging.setdefault(v, (w, cs.pick(inter)))
    div_comps = {comp[v] for v in diverging}
    candidates = [q for q in range(n) if (q * n + q) in comp and comp[q * n + q] in div_comps]
    if not candidates:
        return None

    # prefer the candidate state with the shortest prefix, for a short attack string
    q = min(candidates, key=lambda s: len(_shortest_word(efn, s)))
    diag = q * n + q
    c = comp[diag]

    return _build(efn, q, diag, c, comp, adj, diverging, _shortest_word)


def _build(efn, q, diag, c, comp, adj, diverging, shortest):
    """Closed walk diag -> u -> v (diverging edge) -> diag, as a word."""
    def bfs_nodes(src, is_goal):
        prev = {src: None}
        dq = deque([src])
        while dq:
            v = dq.popleft()
            if is_goal(v):
                chars, node = [], v
                while prev[node] is not None:
                    node, ch = prev[node]
                    chars.append(ch)
                return "".join(reversed(chars)), v
            for w, inter, _ in adj(v):
                if comp.get(w) == c and w not in prev:
                    prev[w] = (v, cs.pick(inter))
                    dq.append(w)
        raise AssertionError("SCC walk not found")

    leg1, u = bfs_nodes(diag, lambda v: v in diverging and comp[v] == c)
    v, step_char = diverging[u]
    leg2, _ = bfs_nodes(v, lambda w: w == diag)
    return EDA(state=q, prefix=shortest(efn, q), pump=leg1 + step_char + leg2)
