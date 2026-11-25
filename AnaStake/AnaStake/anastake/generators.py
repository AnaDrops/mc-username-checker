"""Mode registry. A mode is one function (Options -> Plan) plus one registry line."""
from __future__ import annotations

import hashlib
import itertools
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from . import names as N

PATTERN_CAP = 1_000_000


@dataclass
class Options:
    charset: str = "letters,digits,underscore"
    no_underscore: bool = False
    length: int = 4
    count: int = 100
    random: bool = False
    pattern: str = ""
    prefix: str = ""
    suffix: str = ""
    free: int = 2
    shape: str = "all"
    template: str = "CVCV"
    wordlist: str = ""
    file: str = ""
    min_len: int = 3
    max_len: int = 16
    append_digits: int = 0
    underscore_affix: bool = False
    leet: bool = False
    cap: int = PATTERN_CAP
    seed: int | None = None


@dataclass
class Plan:
    mode: str
    total: int
    items: Callable[[int], Iterator[str]]  # argument: start index
    key: str = ""        # set for resumable sequential runs
    limit: bool = False  # stop after `total` names not already in history
    warning: str = ""


def _key(*parts: object) -> str:
    return hashlib.sha1(repr(parts).encode()).hexdigest()[:16]


def _sequential(mode: str, pools: list[str], cap: int | None = None) -> Plan:
    size = N.product_size(pools)
    total = size if cap is None else min(size, cap)
    warning = f"expansion is {size:,}; capped at {total:,}" if total < size else ""

    def items(start: int = 0) -> Iterator[str]:
        i = start
        while i < total:
            yield N.nth_product(pools, i)
            i += 1

    return Plan(mode, total, items, key=f"{mode}:{_key(pools)}", warning=warning)


def _random(mode: str, pools: list[str], count: int, seed: int | None) -> Plan:
    size = N.product_size(pools)
    total = min(max(count, 0), size)

    def items(start: int = 0) -> Iterator[str]:
        rng = random.Random(seed)
        seen: set[int] = set()
        while len(seen) < size:
            if size <= 2_000_000:  # small space: shuffle once, no rejection loop
                order = list(range(size))
                rng.shuffle(order)
                yield from (N.nth_product(pools, i) for i in order)
                return
            i = rng.randrange(size)
            if i not in seen:
                seen.add(i)
                yield N.nth_product(pools, i)

    return Plan(mode, total, items, limit=True)


def _listed(mode: str, found: list[str], warning: str = "") -> Plan:
    return Plan(mode, len(found), lambda start=0: iter(found[start:]), warning=warning)


def _charset(o: Options) -> str:
    return N.make_charset(o.charset, o.no_underscore)


def _check_length(length: int) -> None:
    if not 3 <= length <= 16:
        raise ValueError("length must be 3-16")


def _fixed(length: int, letters: bool, rand: bool):
    def build(o: Options) -> Plan:
        chars = N.LETTERS if letters else _charset(o)
        mode = f"{'random' if rand else 'seq'}-{length}{'l' if letters else 'c'}"
        pools = [chars] * length
        return _random(mode, pools, o.count, o.seed) if rand else _sequential(mode, pools)
    return build


def mode_length(o: Options) -> Plan:
    _check_length(o.length)
    pools = [_charset(o)] * o.length
    return _random("length", pools, o.count, o.seed) if o.random else _sequential("length", pools)


def mode_words(o: Options) -> Plan:
    if not o.wordlist:
        raise ValueError("words mode needs --wordlist PATH")
    if not 0 <= o.append_digits <= 2:
        raise ValueError("append digits must be 0, 1 or 2")
    lines = Path(o.wordlist).read_text(encoding="utf-8", errors="replace").splitlines()
    return _listed("words", N.filter_words(lines, o.min_len, o.max_len, o.append_digits,
                                           o.underscore_affix, o.leet))


def mode_pattern(o: Options) -> Plan:
    return _sequential("pattern", N.pattern_pools(o.pattern, _charset(o)), cap=o.cap)


def mode_affix(o: Options) -> Plan:
    prefix, suffix = o.prefix.lower(), o.suffix.lower()
    if any(c not in N.LETTERS + N.DIGITS + "_" for c in prefix + suffix):
        raise ValueError("prefix/suffix has invalid characters")
    if o.free < 0:
        raise ValueError("free must be >= 0")
    _check_length(len(prefix) + o.free + len(suffix))
    pools = list(prefix) + [_charset(o)] * o.free + list(suffix)
    return _sequential("affix", pools, cap=o.cap)


def shape_names(shape: str, length: int, chars: str) -> Iterator[str]:
    if shape in ("repeat", "all"):
        yield from (c * length for c in chars)
    if shape in ("alternate", "all"):
        for a, b in itertools.permutations(chars, 2):
            yield "".join(a if i % 2 == 0 else b for i in range(length))
    if shape in ("palindrome", "all"):
        half = (length + 1) // 2
        for t in itertools.product(chars, repeat=half):
            left = "".join(t)
            yield left + left[: length // 2][::-1]


def mode_shapes(o: Options) -> Plan:
    _check_length(o.length)
    if o.shape not in ("repeat", "alternate", "palindrome", "all"):
        raise ValueError("shape: repeat, alternate, palindrome or all")
    chars = _charset(o)
    if o.shape in ("palindrome", "all") and len(chars) ** ((o.length + 1) // 2) > o.cap:
        raise ValueError("palindrome space exceeds the cap; lower length or charset")
    return _listed("shapes", list(N.dedupe(shape_names(o.shape, o.length, chars))))


def mode_pronounce(o: Options) -> Plan:
    t = o.template.upper()
    _check_length(len(t))
    if set(t) - {"C", "V"}:
        raise ValueError("template uses only C and V")
    return _sequential("pronounce", [N.CONSONANTS if c == "C" else N.VOWELS for c in t])


def mode_numbers(o: Options) -> Plan:
    _check_length(o.length)
    return _sequential("numbers", [N.DIGITS] * o.length)


def mode_consonants(o: Options) -> Plan:
    _check_length(o.length)
    return _sequential("consonants", [N.CONSONANTS] * o.length)


def mode_import(o: Options) -> Plan:
    if not o.file:
        raise ValueError("import mode needs --file PATH")
    lines = Path(o.file).read_text(encoding="utf-8-sig", errors="replace").splitlines()
    cleaned = [x.strip().lower() for x in lines if x.strip()]
    good = list(N.dedupe(x for x in cleaned if N.is_valid(x)))
    bad = sum(not N.is_valid(x) for x in cleaned)
    return _listed("import", good, f"{bad} invalid lines dropped" if bad else "")


MODES: dict[str, Callable[[Options], Plan]] = {
    **{f"seq-{n}{k}": _fixed(n, k == "l", False) for n in (3, 4) for k in "lc"},
    **{f"random-{n}{k}": _fixed(n, k == "l", True) for n in (3, 4) for k in "lc"},
    "length": mode_length,
    "words": mode_words,
    "pattern": mode_pattern,
    "affix": mode_affix,
    "shapes": mode_shapes,
    "pronounce": mode_pronounce,
    "numbers": mode_numbers,
    "consonants": mode_consonants,
    "import": mode_import,
}


def build_plan(mode: str, options: Options) -> Plan:
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}")
    return MODES[mode](options)
