import asyncio

import pytest

from anastake import names as N
from anastake.backend import (AvailabilityBackend, RateLimited, Result, Transient,
                              map_lookup, map_verify)
from anastake.generators import Options, build_plan
from anastake.output import Writer
from anastake.ratelimit import Limiter
from anastake.runner import Runner
from anastake.store import Store


@pytest.mark.parametrize("name,ok", [("ab", False), ("abc", True), ("a" * 16, True),
                                     ("a" * 17, False), ("ab-c", False), ("ab c", False),
                                     ("abc\n", False), ("äbc", False), ("A_9", True)])
def test_validation(name, ok):
    assert N.is_valid(name) is ok


@pytest.mark.parametrize("mode,total", [("seq-3l", 26**3), ("seq-3c", 37**3),
                                        ("seq-4l", 26**4), ("seq-4c", 37**4)])
def test_counts(mode, total):
    assert build_plan(mode, Options()).total == total


def test_full_3l_enumeration_and_resume():
    plan = build_plan("seq-3l", Options())
    names = list(plan.items(0))
    assert len(set(names)) == 26**3 and names[0] == "aaa" and names[-1] == "zzz"
    assert next(plan.items(27)) == names[27]


def test_pattern():
    assert len(list(N.expand_pattern("ab??", N.LETTERS))) == 676
    assert len(list(N.expand_pattern("x#y*", N.make_charset()))) == 370
    capped = build_plan("pattern", Options(pattern="????", cap=10))
    assert capped.total == 10 and capped.warning
    with pytest.raises(ValueError):
        build_plan("pattern", Options(pattern="a-?"))


def test_wordlist_filter_and_dedupe():
    assert N.filter_words([" Cat \n", "cat", "hi", "bad word", "x" * 17]) == ["cat"]
    extra = N.filter_words(["sat"], append_digits=1, underscore=True, leet=True)
    assert {"sat7", "_sat", "sat_", "547"} <= set(extra) and len(extra) == len(set(extra))


def test_random_unique_and_long():
    plan = build_plan("length", Options(length=16, random=True, count=50, seed=1))
    it = plan.items(0)
    assert len({next(it) for _ in range(50)}) == 50


def test_shapes():
    plan = build_plan("shapes", Options(length=4, charset="letters"))
    names = set(plan.items(0))
    assert {"aaaa", "abab", "abba"} <= names and len(names) == plan.total


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"id":"1","name":"Abc"}', "TAKEN"),
    (200, "{}", "ERROR"), (200, "<html>", "ERROR"),
    (404, '{"errorMessage":"x"}', "NOT_FOUND"), (404, "<html>", "ERROR"),
    (204, "", "ERROR"), (403, "{}", "ERROR"), (500, "", "ERROR"), (999, "", "ERROR")])
def test_lookup_mapping(status, body, expected):
    assert map_lookup(status, body, "abc").status == expected


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"status":"AVAILABLE"}', "VERIFIED_AVAILABLE"),
    (200, '{"status":"DUPLICATE"}', "TAKEN"),
    (200, '{"status":"NOT_ALLOWED"}', "BLOCKED"),
    (200, '{"status":"NEW"}', "ERROR"), (401, '{"status":"AVAILABLE"}', "ERROR")])
def test_verify_mapping(status, body, expected):
    assert map_verify(status, body).status == expected


def test_backoff_and_slowdown():
    now = [0.0]
    limiter = Limiter(delay=1, clock=lambda: now[0])
    for _ in range(3):
        assert limiter.limited(7) >= 7
        now[0] += 1000
    assert limiter.delay == 2


class Mock(AvailabilityBackend):
    def __init__(self):
        self.calls = []

    async def lookup(self, name):
        self.calls.append(name)
        if name == "bbb":
            raise Transient("down")
        if name == "ccc" and self.calls.count("ccc") == 1:
            raise RateLimited(0)
        return Result("NOT_FOUND" if name == "aaa" else "TAKEN")


def run_import(tmp_path, backend, **kwargs):
    source = tmp_path / "in.txt"
    source.write_text("AAA\nbbb\nccc\nccc\n!!\n")

    async def go():
        store, writer = Store(str(tmp_path / "db")), Writer(str(tmp_path))
        limiter = Limiter(delay=0, min_delay=0, base=0.001)
        runner = Runner(build_plan("import", Options(file=str(source))), backend, store,
                        writer, limiter, retries=1, **kwargs)
        await runner.run()
        writer.close()
        store.close()
        return runner

    return asyncio.run(go())


def test_runner_with_mock_and_history(tmp_path):
    backend = Mock()
    runner = run_import(tmp_path, backend)
    assert runner.counts["NOT_FOUND"] == 1 and runner.counts["TAKEN"] == 1
    assert runner.counts["ERROR"] == 1 and backend.calls.count("bbb") == 4  # 2 + final pass
    assert (tmp_path / "available.txt").read_text() == "aaa\n"
    again = run_import(tmp_path, Mock())
    assert again.skipped == 2 and again.counts["ERROR"] == 1


def test_stop_keeps_resume_position(tmp_path):
    class Stopper(Mock):
        runner = None

        async def lookup(self, name):
            if name == "aae":
                self.runner.stop.set()
            return Result("TAKEN")

    async def go():
        store, writer = Store(str(tmp_path / "db")), Writer(str(tmp_path))
        plan, backend = build_plan("seq-3l", Options()), Stopper()
        backend.runner = Runner(plan, backend, store, writer,
                                Limiter(delay=0, min_delay=0), concurrency=1)
        await backend.runner.run()
        assert store.position(plan.key) == 5
        writer.close()
        store.close()

    asyncio.run(go())
