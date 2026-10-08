"""nightshift — record every Bot Screen while the Bots work, then hand the user one time-lapse and an honest report."""

import json
from pathlib import Path

from . import schemas
from .nightshift import NightShift, NightShiftError


def _data_dir(ctx) -> Path:
    try:
        return Path(ctx.state.data_dir)
    except Exception:  # older Hermes without plugin state
        from .nightshift import default_root
        return default_root() / "plugin-data" / "nightshift"


def _report(ns: NightShift, run: str | None) -> dict:
    runs = ns.runs()
    if run:
        runs = [p for p in runs if p.name == run]
    if not runs:
        raise NightShiftError("no finished night shift found" + (f" named {run}" if run else ""))
    meta = json.loads((runs[-1] / "run.json").read_text(encoding="utf-8"))
    report = (runs[-1] / "report.md")
    return {"ok": True, "run": meta["id"], "video": meta.get("video"), "report": str(report) if report.exists() else None,
            "markdown": report.read_text(encoding="utf-8") if report.exists() else "(still recording)"}


_SETTINGS = ("wall_port",)


def register(ctx):
    def ns():
        return NightShift(_data_dir(ctx))

    def settings():
        return {k: ctx.get_config(k, default=None) for k in _SETTINGS}

    def tool(fn):
        def handler(args, **_kw):
            try:
                return json.dumps(fn(ns(), args or {}))
            except NightShiftError as e:
                return json.dumps({"ok": False, "error": str(e)})
        return handler

    for name, schema, fn, emoji, blurb in (
        ("nightshift_start", schemas.NIGHTSHIFT_START,
         lambda n, a: n.start(a.get("profiles"), a.get("fps") or 2.0, a.get("label") or ""), "🌙",
         "Record every running Bot Screen"),
        ("nightshift_stop", schemas.NIGHTSHIFT_STOP, lambda n, a: n.stop(a.get("speed") or 20.0), "🌅",
         "Stop, build the time-lapse and the report"),
        ("nightshift_status", schemas.NIGHTSHIFT_STATUS, lambda n, a: n.status(), "📡", "Recording state and screens"),
        ("nightshift_report", schemas.NIGHTSHIFT_REPORT, lambda n, a: _report(n, a.get("run")), "📊",
         "Report of a finished shift"),
        ("nightshift_wall", schemas.NIGHTSHIFT_WALL,
         lambda n, a: n.wall(a.get("action") or "open", a.get("port") or settings().get("wall_port") or 8793), "🖥️",
         "Every Bot Screen live on one page"),
    ):
        ctx.register_tool(name=name, toolset="nightshift", schema=schema, handler=tool(fn), emoji=emoji, description=blurb)

    def _setup(parser):
        parser.add_argument("action", choices=["start", "stop", "status", "report", "wall", "wall-stop"])
        parser.add_argument("--profiles", nargs="*", help="profiles to record (default: every running screen)")
        parser.add_argument("--fps", type=float, default=2.0)
        parser.add_argument("--speed", type=float, default=20.0, help="time-lapse speed-up on stop")
        parser.add_argument("--run", help="run id for report")
        parser.add_argument("--json", action="store_true")

    def _handler(args):
        n = ns()
        try:
            out = {"start": lambda: n.start(args.profiles, args.fps), "stop": lambda: n.stop(args.speed),
                   "status": n.status, "report": lambda: _report(n, args.run),
                   "wall": lambda: n.wall("open", settings().get("wall_port") or 8793),
                   "wall-stop": lambda: n.wall("stop")}[args.action]()
        except NightShiftError as e:
            print(f"nightshift: {e}")
            return 1
        if args.json or args.action in ("start", "status", "wall", "wall-stop"):
            print(json.dumps(out, indent=2))
        else:
            print(out.get("markdown") or json.dumps(out, indent=2))
            if out.get("video"):
                print(f"\nvideo: {out['video']}")
        return 0

    try:
        ctx.register_cli_command(name="nightshift", help="Record Bot Screens into a time-lapse and a report",
                                 setup_fn=_setup, handler_fn=_handler)
    except Exception:  # older Hermes without plugin CLI commands
        pass

    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").exists():
            ctx.register_skill(child.name, child / "SKILL.md")
