"""Rich live panel."""
from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from .session import fmt_duration


def render(s: dict) -> Panel:
    c = s["counts"]
    head = Text(f"mode {s['mode']}   {s['state']}   {s['done']:,}/{s['total']:,}   "
                f"{s['rate']} req/s   eta {fmt_duration(s['eta'])}")
    table = Table("taken", "likely available", "verified", "blocked", "errors", "skipped")
    table.add_row(*(str(x) for x in (c["TAKEN"], c["NOT_FOUND"], c["VERIFIED_AVAILABLE"],
                                     c["BLOCKED"], c["ERROR"], s["skipped"])))
    backoff = Text(f"backoff {s['backoff']}s" if s["backoff"] else "backoff none")
    backoff.append(f"   delay {s['delay']}s   429s {s['rate_limited']}")
    hits = "\n".join(f"{h['name']}  "
                     f"{'verified' if h['status'] == 'VERIFIED_AVAILABLE' else 'likely'}"
                     for h in s["hits"]) or "none yet"
    return Panel(Group(head, ProgressBar(total=max(s["total"], 1), completed=s["done"]),
                       table, backoff, Panel(Text(hits), title="last 10 hits")),
                 title="AnaStake")
