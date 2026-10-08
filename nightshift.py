"""Night Shift core: record every Bot Screen while the Bots work, then build one tiled time-lapse and an
honest report. Everything here is deterministic; the agent only decides when to start and stop.

A Bot Screen is a plain X display (Xvnc), so each one is grabbed with ffmpeg's x11grab. No compositor,
no portal, no tokens: the only inputs are the per-profile ``bot-desktop/`` folder Hermes already keeps
and the profile's ``state.db`` (opened read-only) for what the Bot did meanwhile.
"""

import json
import os
import re
import shlex
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

GRID = {1: ("1", "0_0"), 2: ("2", "0_0|w0_0"), 3: ("2", "0_0|w0_0|0_h0"), 4: ("2", "0_0|w0_0|0_h0|w0_h0"),
        5: ("3", "0_0|w0_0|w0+w1_0|0_h0|w0_h0"), 6: ("3", "0_0|w0_0|w0+w1_0|0_h0|w0_h0|w0+w1_h0")}
TILE_W = 720
STATUS_MARKS = (("✅", "done"), ("✋", "needs you"), ("⚠️", "blocked"), ("⏳", "scheduled"))


class NightShiftError(Exception):
    pass


def default_root() -> Path:
    try:
        from hermes_constants import get_default_hermes_root
        return Path(get_default_hermes_root())
    except Exception:
        return Path.home() / ".hermes"


def _yaml_scalar(path: Path, key: str) -> str:
    """First top-level ``key: value`` in a YAML file, without a YAML dependency."""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(rf"^{re.escape(key)}:\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip("'\"")
    except OSError:
        pass
    return ""


def _motion(config: Path) -> str:
    """``computer_use.cursor_motion`` style from a profile config: a bare value or a ``style:`` child."""
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = re.search(r"^computer_use:\n(?:[ \t]+.*\n)*?[ \t]+cursor_motion:[ \t]*([^\s#]*)", text, re.M)
    if not m:
        return ""
    val = m.group(1).strip("'\"")
    if val:
        return val
    m = re.search(r"cursor_motion:[ \t]*\n(?:[ \t]+.*\n)*?[ \t]+style:[ \t]*([^\s#]+)", text)
    return m.group(1).strip("'\"") if m else ""


def _geometry(config: Path) -> str:
    m = re.search(r"^bot_desktop:\n(?:[ \t]+.*\n)*?[ \t]+geometry:\s*[\"']?(\d+x\d+)", _read(config), re.M)
    return m.group(1) if m else "1440x900"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def bots(root: Path) -> list:
    """Every profile with a Bot Screen folder, running or not."""
    out = []
    homes = [("default", root)]
    prof = root / "profiles"
    if prof.is_dir():
        homes += sorted((d.name, d) for d in prof.iterdir() if d.is_dir())
    for name, home in homes:
        bd = home / "bot-desktop"
        if not bd.is_dir():
            continue
        display = _read(bd / "display").strip()
        out.append({
            "profile": name, "home": str(home),
            "display_name": _yaml_scalar(home / "profile.yaml", "display_name") or name,
            "display": f":{display}" if display and not display.startswith(":") else display,
            "running": bool(display) and (bd / "rfb.sock").exists(),
            "xauthority": str(bd / "Xauthority"), "geometry": _geometry(home / "config.yaml"),
            "motion": _motion(home / "config.yaml") or "default",
        })
    return out


class NightShift:
    def __init__(self, data_dir: Path, root: Path | None = None, spawn=subprocess.Popen, run=subprocess.run,
                 ffmpeg: str = "ffmpeg"):
        self.data = Path(data_dir)
        self.root = Path(root or default_root())
        self.spawn, self.run, self.ffmpeg = spawn, run, ffmpeg

    # ---- state -------------------------------------------------------------------------------
    @property
    def active_file(self) -> Path:
        return self.data / "active.json"

    def _active(self):
        try:
            return json.loads(self.active_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def runs(self):
        d = self.data / "runs"
        return sorted((p for p in d.iterdir() if (p / "run.json").exists()), key=lambda p: p.name) if d.is_dir() else []

    # ---- start / stop ------------------------------------------------------------------------
    def start(self, profiles=None, fps: float = 2.0, label: str = "") -> dict:
        if self._active():
            raise NightShiftError("a night shift is already recording; call nightshift_stop first")
        chosen = [b for b in bots(self.root) if b["running"] and (not profiles or b["profile"] in profiles)]
        missing = [p for p in (profiles or []) if p not in {b["profile"] for b in chosen}]
        if missing:
            raise NightShiftError(f"no running Bot Screen for {', '.join(missing)}: start it with "
                                  "`hermes -p <profile> computer-use screen start` (or the Desktop Screen pane)")
        if not chosen:
            raise NightShiftError("no Bot Screen is running; start one first")
        if len(chosen) > 6:
            raise NightShiftError("at most 6 screens per shift")
        fps = float(fps)
        if not 0.2 <= fps <= 15:
            raise NightShiftError("fps must be between 0.2 and 15 (2 is a good time-lapse rate)")
        run_id = time.strftime("%Y%m%d-%H%M%S")
        run_dir = self.data / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        rec = {}
        for b in chosen:
            out = run_dir / f"{b['profile']}.mp4"
            cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", str(fps),
                   "-video_size", b["geometry"], "-i", b["display"], "-c:v", "libx264", "-preset", "ultrafast",
                   "-pix_fmt", "yuv420p", str(out)]
            env = {**os.environ, "XAUTHORITY": b["xauthority"], "DISPLAY": b["display"]}
            proc = self.spawn(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=open(run_dir / f"{b['profile']}.ffmpeg.log", "ab"))
            rec[b["profile"]] = {**{k: b[k] for k in ("display_name", "display", "motion", "home")},
                                 "file": str(out), "pid": proc.pid}
        meta = {"id": run_id, "label": label, "started": time.time(), "fps": fps, "bots": rec}
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self.active_file.write_text(json.dumps({"id": run_id}), encoding="utf-8")
        return {"ok": True, "run": run_id, "recording": [{"profile": p, "display": v["display"],
                                                           "motion": v["motion"]} for p, v in rec.items()],
                "folder": str(run_dir)}

    def stop(self, speed: float = 20.0) -> dict:
        active = self._active()
        if not active:
            raise NightShiftError("no night shift is recording")
        run_dir = self.data / "runs" / active["id"]
        meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        for v in meta["bots"].values():
            try:
                os.kill(v["pid"], signal.SIGINT)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.time() + 20
        for v in meta["bots"].values():
            _wait_gone(v["pid"], deadline)
        meta["ended"] = time.time()
        self.active_file.unlink(missing_ok=True)
        report = self.build_report(meta)
        video = self.build_video(run_dir, meta, speed)
        meta["video"], meta["report"] = video, str(run_dir / "report.md")
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (run_dir / "report.md").write_text(report["markdown"], encoding="utf-8")
        return {"ok": True, "run": meta["id"], "video": video, "report": str(run_dir / "report.md"), **report}

    def status(self) -> dict:
        active = self._active()
        screens = [{"profile": b["profile"], "display_name": b["display_name"], "display": b["display"],
                    "running": b["running"], "motion": b["motion"]} for b in bots(self.root)]
        if not active:
            return {"ok": True, "recording": False, "screens": screens, "runs": [p.name for p in self.runs()][-5:]}
        meta = json.loads((self.data / "runs" / active["id"] / "run.json").read_text(encoding="utf-8"))
        return {"ok": True, "recording": True, "run": meta["id"], "since_minutes": round((time.time() - meta["started"]) / 60, 1),
                "bots": {p: {"alive": _alive(v["pid"]), "display": v["display"]} for p, v in meta["bots"].items()},
                "screens": screens}

    # ---- live wall ---------------------------------------------------------------------------
    def wall(self, action: str = "open", port: int = 8793) -> dict:
        """Start, query or stop the Bot Wall page (a separate small process; see wall.py)."""
        info = None
        try:
            info = json.loads((self.data / "wall.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        alive = bool(info) and _alive(int(info["pid"]))
        if action == "stop":
            if alive:
                os.kill(int(info["pid"]), signal.SIGTERM)
            (self.data / "wall.json").unlink(missing_ok=True)
            return {"ok": True, "running": False}
        if action == "status":
            return {"ok": True, "running": alive, "url": info["url"] if alive else None}
        if alive:
            return {"ok": True, "running": True, "url": info["url"], "already_running": True}
        self.data.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(Path(__file__).resolve().parent / "wall.py"), "--data", str(self.data),
               "--root", str(self.root), "--port", str(int(port))]
        self.spawn(cmd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=open(self.data / "wall.log", "ab"))
        for _ in range(30):
            try:
                info = json.loads((self.data / "wall.json").read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                time.sleep(0.1)
        url = (info or {}).get("url") or f"http://127.0.0.1:{int(port)}/"
        return {"ok": True, "running": True, "url": url,
                "screens": [b["profile"] for b in bots(self.root) if b["running"]]}

    # ---- outputs -----------------------------------------------------------------------------
    def video_command(self, run_dir: Path, meta: dict, speed: float) -> list:
        files = [(p, v) for p, v in meta["bots"].items() if Path(v["file"]).exists() and Path(v["file"]).stat().st_size > 0]
        if not files:
            return []
        cols, layout = GRID[len(files)]
        parts, inputs = [], []
        for i, (p, v) in enumerate(files):
            inputs += ["-i", v["file"]]
            label = f"{v['display_name']}  ·  cursor {v['motion']}".replace("'", "").replace(":", "\\:")
            parts.append(f"[{i}:v]setpts=PTS/{speed},scale={TILE_W}:-2,"
                         f"drawtext=text='{label}':x=12:y=12:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=8[v{i}]")
        if len(files) == 1:
            graph = parts[0].replace("[v0]", "[out]")
        else:
            graph = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(files))) + \
                    f"xstack=inputs={len(files)}:layout={layout}:fill=black[out]"
        out = run_dir / "nightshift.mp4"
        return [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", graph,
                "-map", "[out]", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)]

    def build_video(self, run_dir: Path, meta: dict, speed: float) -> str | None:
        cmd = self.video_command(run_dir, meta, speed)
        if not cmd:
            return None
        res = self.run(cmd, capture_output=True, text=True, timeout=1800)
        if res.returncode != 0:
            (run_dir / "video.error.log").write_text((res.stderr or "")[-4000:], encoding="utf-8")
            return None
        return cmd[-1]

    def build_report(self, meta: dict) -> dict:
        since, until = meta["started"], meta.get("ended") or time.time()
        rows = []
        for p, v in meta["bots"].items():
            rows.append({"profile": p, "display_name": v["display_name"], "motion": v["motion"],
                         **session_facts(Path(v["home"]) / "state.db", since, until)})
        mins = round((until - since) / 60)
        lines = [f"**Night Shift {meta['id']}** · {len(rows)} Bots · {mins} min" + (f" · {meta['label']}" if meta.get("label") else ""), ""]
        lines.append("| Bot | cursor | sessions | screen actions | status | needed a human |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows:
            lines.append(f"| {r['display_name']} | {r['motion']} | {r['sessions']} | {r['actions']} | {r['status']} | {r['interventions']} |")
        lines += ["", "Last word from each Bot:"]
        for r in rows:
            lines.append(f"- **{r['display_name']}**: {r['last'] or '(no reply recorded)'}")
        lines += ["", f"Humans stepped in {sum(r['interventions'] for r in rows)} time(s) across the shift."]
        return {"bots": rows, "minutes": mins, "markdown": "\n".join(lines)}


def _wait_gone(pid: int, deadline: float) -> None:
    """Wait for a recorder to exit, reaping it when it is our child (a SIGINT'd ffmpeg stays a zombie,
    which os.kill(pid, 0) still counts as alive, until someone collects it)."""
    while time.time() < deadline:
        try:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return
        except ChildProcessError:  # not our child (plugin host restarted): fall back to liveness polling
            if not _alive(pid):
                return
        time.sleep(0.2)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def session_facts(db: Path, since: float, until: float) -> dict:
    """What a profile did between two times, from its own state.db (read-only): sessions touched,
    computer_use/browser actions, how many times a tool was refused because a human held the screen,
    and the Bot's last reply with its ack mark turned into a status."""
    empty = {"sessions": 0, "actions": 0, "interventions": 0, "status": "no activity", "last": ""}
    if not db.exists():
        return empty
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        cols = {r[1] for r in c.execute("pragma table_info(messages)")}
        if not {"role", "content", "session_id", "timestamp"} <= cols:
            return empty
        tool_col = "tool_name" if "tool_name" in cols else "NULL"
        rows = c.execute(f"select session_id, role, {tool_col}, coalesce(content,''), timestamp from messages "
                         "where timestamp between ? and ? order by timestamp", (_ts(since, c), _ts(until, c))).fetchall()
    except sqlite3.Error:
        return empty
    sessions = {r[0] for r in rows}
    actions = sum(1 for r in rows if r[1] == "tool" and (r[2] or "") in ("computer_use", "browser_navigate", "browser_click"))
    interventions = sum(1 for r in rows if r[1] == "tool" and "human_has_control" in r[3])
    last = next((r[3].strip() for r in reversed(rows) if r[1] == "assistant" and r[3].strip()), "")
    status = next((name for mark, name in STATUS_MARKS if last.startswith(mark)), "unknown" if last else "no reply")
    return {"sessions": len(sessions), "actions": actions, "interventions": interventions, "status": status,
            "last": re.sub(r"\s+", " ", last)[:200]}


def _ts(t: float, conn) -> object:
    """state.db timestamps are ISO strings on some builds and epoch floats on others; match the column."""
    try:
        sample = conn.execute("select timestamp from messages where timestamp is not null limit 1").fetchone()
    except sqlite3.Error:
        sample = None
    if sample and isinstance(sample[0], str):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))
    return t


def human_command(cmd: list) -> str:
    return " ".join(shlex.quote(c) for c in cmd)
