"""Regex parser: pattern string -> AST.

Supported: literals, '.', classes [a-z] / [^...], \\d \\w \\s (and negations), escapes,
grouping (...) and (?:...), alternation |, quantifiers * + ? {n} {n,} {n,m} (n, m <= 50),
and ^ / $ at the very start / end. Matching is always a full match.

Not supported (these are not regular, or out of scope): backreferences, lookaround,
\\b, possessive quantifiers. Lazy quantifiers (a+?) are accepted and treated as greedy.
"""
import re

from . import charset as cs

MAX_REPEAT = 50
_BRACE = re.compile(r"\{(\d+)(?:(,)(\d*))?\}")


class RegexSyntaxError(ValueError):
    def __init__(self, msg, pos=None):
        super().__init__(msg)
        self.msg, self.pos = msg, pos


class Empty:
    pass


class CharSet:
    def __init__(self, mask):
        self.mask = mask


class Cat:
    def __init__(self, parts):
        self.parts = parts


class Alt:
    def __init__(self, options):
        self.options = options


class Star:
    def __init__(self, child):
        self.child = child


class Plus(Star):
    pass


class Opt(Star):
    pass


def _expand(node, lo, hi):
    """x{lo,hi} as Cat/Opt/Star nodes (hi=None means unbounded)."""
    parts = [node] * lo
    if hi is None:
        parts.append(Star(node))
    else:
        tail = None
        for _ in range(hi - lo):
            tail = Opt(Cat([node, tail]) if tail is not None else node)
        if tail is not None:
            parts.append(tail)
    if not parts:
        return Empty()
    return parts[0] if len(parts) == 1 else Cat(parts)


class _Parser:
    def __init__(self, s, offset=0):
        self.s, self.i, self.offset = s, 0, offset

    def peek(self):
        return self.s[self.i] if self.i < len(self.s) else ""

    def err(self, msg):
        raise RegexSyntaxError(msg, self.i + self.offset)

    def parse(self):
        node = self.alt()
        if self.i < len(self.s):
            self.err("unmatched ')'")
        return node

    def alt(self):
        opts = [self.cat()]
        while self.peek() == "|":
            self.i += 1
            opts.append(self.cat())
        return opts[0] if len(opts) == 1 else Alt(opts)

    def cat(self):
        parts = []
        while self.peek() and self.peek() not in "|)":
            parts.append(self.repeat())
        if not parts:
            return Empty()
        return parts[0] if len(parts) == 1 else Cat(parts)

    def repeat(self):
        node = self.atom()
        c = self.peek()
        if c and c in "*+?":
            self.i += 1
            node = {"*": Star, "+": Plus, "?": Opt}[c](node)
        elif c == "{":
            m = _BRACE.match(self.s, self.i)
            if not m:
                self.err("bad {n,m} quantifier")
            lo = int(m.group(1))
            hi = lo if m.group(2) is None else (None if m.group(3) == "" else int(m.group(3)))
            if lo > MAX_REPEAT or (hi is not None and hi > MAX_REPEAT):
                self.err(f"repeat counts above {MAX_REPEAT} are not supported")
            if hi is not None and hi < lo:
                self.err("bad {n,m} quantifier: m < n")
            self.i = m.end()
            node = _expand(node, lo, hi)
        else:
            return node
        if self.peek() == "?":  # lazy marker, language unchanged
            self.i += 1
        elif self.peek() == "+":
            self.err("possessive quantifiers are not supported")
        p = self.peek()
        if p and p in "*+?{":
            self.err("multiple repeat")
        return node

    def atom(self):
        c = self.peek()
        if c == "(":
            self.i += 1
            if self.peek() == "?":
                if self.s.startswith("?:", self.i):
                    self.i += 2
                else:
                    self.err("only (?:...) groups are supported (no lookaround or named groups)")
            node = self.alt()
            if self.peek() != ")":
                self.err("missing ')'")
            self.i += 1
            return node
        if c == "[":
            return self.cls()
        if c == ".":
            self.i += 1
            return CharSet(cs.DOT)
        if c == "\\":
            return CharSet(self.escape())
        if c in ("*", "+", "?"):
            self.err("nothing to repeat")
        if c == "{":
            self.err("escape a literal '{' as \\{")
        if c in ("^", "$"):
            self.err("^ and $ are only supported at the very start / end of the pattern")
        self.i += 1
        return CharSet(self.lit(c))

    def lit(self, c):
        try:
            return cs.bit(c)
        except ValueError as e:
            self.err(str(e))

    def escape(self):
        self.i += 1
        c = self.peek()
        if not c:
            self.err("trailing backslash")
        self.i += 1
        table = {
            "d": cs.DIGIT, "D": cs.FULL & ~cs.DIGIT,
            "w": cs.WORD, "W": cs.FULL & ~cs.WORD,
            "s": cs.SPACE, "S": cs.FULL & ~cs.SPACE,
            "t": cs.bit("\t"), "n": cs.bit("\n"), "r": cs.bit("\r"),
            "f": cs.bit("\f"), "v": cs.bit("\v"),
        }
        if c in table:
            return table[c]
        if c.isalnum():
            self.i -= 1
            self.err(f"unsupported escape \\{c} (backreferences and \\b are not regular)")
        return self.lit(c)

    def class_atom(self):
        if self.peek() == "\\":
            m = self.escape()
            single = chr(cs.LO + m.bit_length() - 1) if m & (m - 1) == 0 else None
            return m, single
        c = self.peek()
        self.i += 1
        return self.lit(c), c

    def cls(self):
        self.i += 1
        neg = False
        if self.peek() == "^":
            neg = True
            self.i += 1
        mask, first = 0, True
        while True:
            c = self.peek()
            if not c:
                self.err("missing ']'")
            if c == "]" and not first:
                self.i += 1
                break
            first = False
            lo_mask, lo_ch = self.class_atom()
            nxt = self.s[self.i + 1 : self.i + 2]
            if self.peek() == "-" and nxt not in ("", "]"):
                if lo_ch is None:
                    self.err("bad range in character class")
                self.i += 1
                hi_mask, hi_ch = self.class_atom()
                if hi_ch is None or ord(hi_ch) < ord(lo_ch):
                    self.err("bad range in character class")
                mask |= cs.from_range(lo_ch, hi_ch)
            else:
                mask |= lo_mask
        return CharSet(cs.FULL & ~mask if neg else mask)


def parse(pattern):
    s, offset = pattern, 0
    if s.startswith("^"):
        s, offset = s[1:], 1
    if s.endswith("$"):
        backslashes, k = 0, len(s) - 2
        while k >= 0 and s[k] == "\\":
            backslashes += 1
            k -= 1
        if backslashes % 2 == 0:
            s = s[:-1]
    return _Parser(s, offset).parse()
