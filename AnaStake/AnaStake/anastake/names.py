"""Pure name rules, charsets, pattern expansion and wordlist filtering."""
from __future__ import annotations

import itertools
import re
import string
from collections.abc import Iterable, Iterator

NAME_RE = re.compile(r"[A-Za-z0-9_]{3,16}")
LETTERS = string.ascii_lowercase
DIGITS = string.digits
VOWELS = "aeiou"
CONSONANTS = "".join(c for c in LETTERS if c not in VOWELS)
LEET = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7"}


def is_valid(name: str) -> bool:
    return NAME_RE.fullmatch(name) is not None


def make_charset(spec: str = "letters,digits,underscore", no_underscore: bool = False) -> str:
    parts = {"letters": LETTERS, "digits": DIGITS, "underscore": "_"}
    wanted = [p.strip() for p in spec.split(",") if p.strip()]
    unknown = [p for p in wanted if p not in parts]
    if unknown or not wanted:
        raise ValueError(f"bad charset {spec!r}; use letters,digits,underscore")
    chars = "".join(v for k, v in parts.items()
                    if k in wanted and not (k == "underscore" and no_underscore))
    if not chars:
        raise ValueError("charset is empty")
    return chars


def nth_product(pools: list[str], index: int) -> str:
    out = []
    for pool in reversed(pools):
        index, r = divmod(index, len(pool))
        out.append(pool[r])
    return "".join(reversed(out))


def product_size(pools: list[str]) -> int:
    size = 1
    for pool in pools:
        size *= len(pool)
    return size


def pattern_pools(pattern: str, charset: str) -> list[str]:
    wild = {"?": LETTERS, "#": DIGITS, "*": charset}
    pattern = pattern.lower()
    if not 3 <= len(pattern) <= 16:
        raise ValueError("pattern length must be 3-16")
    pools = []
    for ch in pattern:
        if ch in wild:
            pools.append(wild[ch])
        elif is_valid(ch * 3):
            pools.append(ch)
        else:
            raise ValueError(f"bad pattern character {ch!r}")
    return pools


def expand_pattern(pattern: str, charset: str) -> Iterator[str]:
    return ("".join(t) for t in itertools.product(*pattern_pools(pattern, charset)))


def dedupe(names: Iterable[str]) -> Iterator[str]:
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            yield name


def leet_variants(word: str) -> Iterator[str]:
    """Each single substitution, plus all substitutions at once."""
    for i, ch in enumerate(word):
        if ch in LEET:
            yield word[:i] + LEET[ch] + word[i + 1:]
    yield "".join(LEET.get(c, c) for c in word)


def filter_words(lines: Iterable[str], min_len: int = 3, max_len: int = 16,
                 append_digits: int = 0, underscore: bool = False,
                 leet: bool = False) -> list[str]:
    def ok(w: str) -> bool:
        return is_valid(w) and min_len <= len(w) <= max_len

    out: list[str] = []
    for line in lines:
        word = line.strip().lstrip("﻿").lower()
        if not word or not re.fullmatch(r"[a-z0-9_]+", word):
            continue
        variants = [word]
        if leet:
            variants += leet_variants(word)
        for n in range(1, append_digits + 1):
            variants += [f"{word}{i:0{n}d}" for i in range(10 ** n)]
        if underscore:
            variants += [f"_{word}", f"{word}_"]
        out += [v for v in variants if ok(v)]
    return list(dedupe(out))
