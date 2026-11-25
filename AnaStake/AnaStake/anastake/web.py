"""Local dashboard server. Binds to 127.0.0.1 only."""
from __future__ import annotations

import asyncio
from dataclasses import fields, replace
from pathlib import Path

from aiohttp import web

from . import config
from .generators import MODES, Options, build_plan
from .session import Settings, estimate, execute
from .store import Store

PAGE = Path(__file__).with_name("static") / "index.html"


def parse_options(data: dict) -> Options:
    kwargs = {}
    for f in fields(Options):
        value = data.get(f.name)
        if value in (None, ""):
            continue
        if f.type == "bool":
            kwargs[f.name] = bool(value)
        elif f.type.startswith("int"):
            kwargs[f.name] = int(value)
        else:
            kwargs[f.name] = str(value)
    return Options(**kwargs)


def make_app(settings: Settings, port: int) -> web.Application:
    run: dict = {"runner": None, "task": None, "error": ""}
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @web.middleware
    async def guard(request, handler):
        # blocks DNS rebinding and cross-site form posts
        if request.host not in allowed:
            raise web.HTTPForbidden()
        if request.method == "POST" and request.headers.get("X-AnaStake") != "1":
            raise web.HTTPForbidden()
        try:
            return await handler(request)
        except (ValueError, OSError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    async def index(_):
        return web.FileResponse(PAGE)

    async def state(_):
        runner = run["runner"]
        busy = bool(run["task"] and not run["task"].done())
        return web.json_response({"busy": busy, "error": run["error"], "modes": list(MODES),
                                  "run": runner.snapshot() if runner else None})

    def prepare(data: dict):
        plan = build_plan(data.get("mode", ""), parse_options(data))
        s = replace(settings,
                    delay=max(float(data.get("delay") or settings.delay), config.MIN_DELAY),
                    concurrency=min(max(int(data.get("concurrency") or settings.concurrency), 1), 10),
                    verify=bool(data.get("verify")),
                    ignore_history=bool(data.get("ignore_history")))
        return plan, s

    async def preview(request):
        plan, s = prepare(await request.json())
        sample = []
        for name in plan.items(0):
            if len(sample) >= min(60, plan.total):
                break
            sample.append(name)
        return web.json_response({"total": plan.total, "seconds": estimate(plan.total, s.delay),
                                  "warning": plan.warning, "sample": sample,
                                  "confirm": plan.total > s.confirm_above})

    async def start(request):
        data = await request.json()
        if run["task"] and not run["task"].done():
            raise ValueError("a run is already active")
        plan, s = prepare(data)
        if plan.total > s.confirm_above and not data.get("confirmed"):
            raise ValueError("large run needs confirmation")

        async def job():
            try:
                await execute(plan, s, lambda r: run.update(runner=r))
            except Exception as exc:  # surfaced in the dashboard
                run["error"] = f"{type(exc).__name__}: {exc}"

        run.update(error="", runner=None, task=asyncio.create_task(job()))
        return web.json_response({"ok": True})

    async def stop(_):
        if run["runner"]:
            run["runner"].stop.set()
        return web.json_response({"ok": True})

    async def results(_):
        store = Store(settings.db)
        try:
            rows = store.recent()
        finally:
            store.close()
        return web.json_response([{"name": n, "status": s, "at": t, "mode": m}
                                  for n, s, t, m in rows])

    async def shutdown(_):
        if run["runner"]:
            run["runner"].stop.set()
        if run["task"]:
            await run["task"]

    app = web.Application(middlewares=[guard])
    app.add_routes([web.get("/", index), web.get("/api/state", state),
                    web.get("/api/results", results), web.post("/api/preview", preview),
                    web.post("/api/start", start), web.post("/api/stop", stop)])
    app.on_shutdown.append(shutdown)
    return app


def serve(settings: Settings, port: int = 8765) -> None:
    print(f"AnaStake dashboard: http://127.0.0.1:{port}  (Ctrl+C to quit)")
    web.run_app(make_app(settings, port), host="127.0.0.1", port=port, print=None)
