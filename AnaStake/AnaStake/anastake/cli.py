"""argparse CLI, interactive menu, Ctrl+C handling."""
from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import fields

from . import config
from .generators import MODES, Options, Plan, build_plan
from .session import Settings, estimate, execute, fmt_duration


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anastake", description="Minecraft name availability checker")
    p.add_argument("mode", nargs="?", choices=[*MODES, "gui"])
    d = Options()
    for name in ("charset", "pattern", "prefix", "suffix", "template", "wordlist", "file"):
        p.add_argument(f"--{name}", default=getattr(d, name))
    p.add_argument("--shape", default="all", choices=["repeat", "alternate", "palindrome", "all"])
    for name in ("length", "count", "free", "min-len", "max-len", "cap"):
        p.add_argument(f"--{name}", type=int, default=getattr(d, name.replace("-", "_")))
    p.add_argument("--append-digits", type=int, default=0, choices=[0, 1, 2])
    p.add_argument("--seed", type=int)
    for name in ("no-underscore", "random", "underscore-affix", "leet", "verify",
                 "ignore-history", "yes"):
        p.add_argument(f"--{name}", action="store_true")
    s = Settings()
    p.add_argument("--concurrency", type=int, default=s.concurrency)
    p.add_argument("--delay", type=float, default=s.delay)
    p.add_argument("--max-age", type=float, default=s.max_age, help="history age in hours")
    p.add_argument("--db", default=s.db)
    p.add_argument("--out", default=s.out)
    p.add_argument("--confirm-above", type=int, default=config.CONFIRM_THRESHOLD)
    p.add_argument("--port", type=int, default=8765)
    return p


def menu() -> list[str]:
    modes = [*MODES, "gui"]
    for i, mode in enumerate(modes, 1):
        print(f"{i:>2}. {mode}")
    mode = modes[int(input("mode number: ")) - 1]
    args = [mode]
    asks = {"words": ["wordlist"], "import": ["file"], "pattern": ["pattern"],
            "affix": ["prefix", "suffix", "free"], "shapes": ["shape", "length"],
            "pronounce": ["template"], "length": ["length"], "numbers": ["length"],
            "consonants": ["length"]}.get(mode, [])
    if mode.startswith("random"):
        asks = ["count"]
    for name in asks:
        value = input(f"{name} (blank = default): ").strip()
        if value:
            args.append(f"--{name}={value}")
    if mode == "length" and input("random order? [y/N] ").lower() == "y":
        args.append("--random")
        args.append(f"--count={input('count: ').strip() or 100}")
    return args


async def run_terminal(plan: Plan, settings: Settings) -> None:
    from rich.live import Live

    from .ui import render

    holder: dict = {}
    loop = asyncio.get_running_loop()

    def request_stop(*_):
        if "runner" in holder:
            loop.call_soon_threadsafe(holder["runner"].stop.set)

    previous = signal.signal(signal.SIGINT, request_stop)
    try:
        task = asyncio.create_task(execute(plan, settings, lambda r: holder.update(runner=r)))
        with Live(refresh_per_second=4) as live:
            while not task.done():
                if "runner" in holder:
                    live.update(render(holder["runner"].snapshot()))
                await asyncio.wait([task], timeout=0.25)
            runner = await task
            live.update(render(runner.snapshot()))
    finally:
        signal.signal(signal.SIGINT, previous)


def main(argv: list[str] | None = None) -> int:
    import sys

    argv = sys.argv[1:] if argv is None else argv
    try:
        args = parser().parse_args(argv or menu())
        if args.mode is None:
            parser().error("a mode is required")
        settings = Settings(**{f.name: getattr(args, f.name) for f in fields(Settings)})
        if args.mode == "gui":
            from .web import serve

            serve(settings, args.port)
            return 0
        plan = build_plan(args.mode, Options(**{f.name: getattr(args, f.name)
                                                for f in fields(Options)}))
        if plan.warning:
            print("warning:", plan.warning)
        print(f"candidates: {plan.total:,}   estimated at least "
              f"{fmt_duration(estimate(plan.total, settings.delay))}")
        if not args.yes and plan.total > settings.confirm_above:
            if input("large run. continue? [y/N] ").strip().lower() != "y":
                return 1
        elif not args.yes and input("start? [Y/n] ").strip().lower() == "n":
            return 1
        asyncio.run(run_terminal(plan, settings))
        return 0
    except (ValueError, OSError, IndexError) as exc:
        print("error:", exc)
        return 2
    except (KeyboardInterrupt, EOFError):
        return 130
