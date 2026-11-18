"""Character sets stored as integer bitmasks over a small fixed alphabet (ASCII 9..126).

Intersection is `a & b` and "is empty" is `not mask`, which keeps the NFA product
construction in ambiguity.py cheap.
"""

LO, HI = 9, 126
SIZE = HI - LO + 1
FULL = (1 << SIZE) - 1


def bit(c):
    o = ord(c)
    if not LO <= o <= HI:
        raise ValueError(f"character U+{o:04X} is outside the supported ASCII range")
    return 1 << (o - LO)


def from_chars(chars):
    mask = 0
    for c in chars:
        mask |= bit(c)
    return mask


def from_range(a, b):
    lo, hi = ord(a), ord(b)
    bit(a), bit(b)  # validate
    return ((1 << (hi - lo + 1)) - 1) << (lo - LO)


DIGIT = from_range("0", "9")
UPPER = from_range("A", "Z")
LOWER = from_range("a", "z")
ALNUM = DIGIT | UPPER | LOWER
WORD = ALNUM | bit("_")
SPACE = from_chars(" \t\n\r\f\v")
DOT = FULL & ~bit("\n")


def contains(mask, c):
    o = ord(c)
    return LO <= o <= HI and bool(mask >> (o - LO) & 1)


def pick(mask):
    """A representative character from a non-empty mask, preferring letters/digits."""
    m = (mask & ALNUM) or mask
    return chr(LO + (m & -m).bit_length() - 1)


_ESC = {"\t": "\\t", "\n": "\\n", "\r": "\\r", "\f": "\\f", "\v": "\\v", " ": "␣"}


def _name(i):
    c = chr(LO + i)
    if c in _ESC:
        return _ESC[c]
    return c if 33 <= ord(c) <= 126 else "\\x%02x" % ord(c)


def label(mask):
    """Short human-readable label for a charset (used in the Graphviz output)."""
    if mask == FULL:
        return "any"
    if mask == DOT:
        return "."
    idx = [i for i in range(SIZE) if mask >> i & 1]
    neg = len(idx) > SIZE // 2
    if neg:
        idx = [i for i in range(SIZE) if not mask >> i & 1]
    if len(idx) == 1 and not neg:
        return _name(idx[0])
    parts, i = [], 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{_name(idx[i])}-{_name(idx[j])}")
        else:
            parts.extend(_name(k) for k in idx[i : j + 1])
        i = j + 1
    return ("[^" if neg else "[") + "".join(parts) + "]"
