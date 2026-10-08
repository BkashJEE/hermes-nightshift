import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nightshift import GRID, NightShift, NightShiftError, bots, session_facts  # noqa: E402


class FakeSpawn:
    """Records ffmpeg invocations and stands in a real, harmless child (``sleep``) so stop()'s
    SIGINT + wait path runs for real."""

    def __init__(self):
        self.calls, self.procs = [], []

    def __call__(self, cmd, env=None, **kw):
        self.calls.append((cmd, env))
        proc = subprocess.Popen(["sleep", "60"])
        self.procs.append(proc)
        return proc

    def cleanup(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()


class FakeRun:
    def __init__(self, rc=0):
        self.rc, self.calls = rc, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"mp4")

        class R:
            returncode, stderr = self.rc, "boom"
        return R()


def make_profile(root: Path, name: str, display: str, running=True, motion="magnetic", display_name=None,
                 geometry=None):
    home = root / "profiles" / name
    bd = home / "bot-desktop"
    bd.mkdir(parents=True)
    (bd / "display").write_text(display)
    (bd / "Xauthority").write_bytes(b"")
    if running:
        (bd / "rfb.sock").write_bytes(b"")
    (home / "profile.yaml").write_text(f"display_name: {display_name or name.title()} — Bot\ndescription: x\n")
    cfg = "terminal:\n  backend: local\ncomputer_use:\n  no_overlay: false\n  cursor_motion: " + motion + "\n"
    if geometry:
        cfg += f"bot_desktop:\n  geometry: \"{geometry}\"\n"
    (home / "config.yaml").write_text(cfg)
    return home


def seed_db(home: Path, rows, iso=False):
    c = sqlite3.connect(home / "state.db")
    c.execute("create table messages(id integer primary key, session_id text, role text, content text, tool_name text, timestamp real)")
    c.execute("create table sessions(id text)")
    for sid, role, content, tool, ts in rows:
        t = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts)) if iso else ts
        c.execute("insert into messages(session_id, role, content, tool_name, timestamp) values(?,?,?,?,?)", (sid, role, content, tool, t))
    c.commit()
    c.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hermes"
        self.data = Path(self.tmp.name) / "data"
        self.spawn, self.run = FakeSpawn(), FakeRun()

    def tearDown(self):
        self.spawn.cleanup()
        self.tmp.cleanup()

    def ns(self):
        return NightShift(self.data, self.root, spawn=self.spawn, run=self.run, ffmpeg="ffmpeg")


class Discovery(Base):
    def test_lists_profiles_with_screens(self):
        make_profile(self.root, "ceo", "20", motion="magnetic")
        make_profile(self.root, "nova", "22", running=False, geometry="1280x800")
        (self.root / "profiles" / "plain").mkdir()
        found = {b["profile"]: b for b in bots(self.root)}
        self.assertEqual(set(found), {"ceo", "nova"})
        self.assertEqual((found["ceo"]["display"], found["ceo"]["running"], found["ceo"]["motion"]), (":20", True, "magnetic"))
        self.assertEqual((found["nova"]["running"], found["nova"]["geometry"]), (False, "1280x800"))
        self.assertEqual(found["ceo"]["display_name"], "Ceo — Bot")

    def test_nested_motion_style(self):
        home = make_profile(self.root, "ceo", "20")
        (home / "config.yaml").write_text("computer_use:\n  cursor_motion:\n    style: comet_swoop\n    timing: fitts\n")
        self.assertEqual(bots(self.root)[0]["motion"], "comet_swoop")


class StartStop(Base):
    def test_start_records_running_screens_only(self):
        make_profile(self.root, "ceo", "20", motion="magnetic")
        make_profile(self.root, "sanju", "21", motion="comet_swoop")
        make_profile(self.root, "nova", "22", running=False)
        out = self.ns().start()
        self.assertEqual({r["profile"] for r in out["recording"]}, {"ceo", "sanju"})
        self.assertEqual(len(self.spawn.calls), 2)
        cmd, env = self.spawn.calls[0]
        self.assertIn("x11grab", cmd)
        self.assertEqual(cmd[cmd.index("-i") + 1], ":20")
        self.assertEqual(cmd[cmd.index("-video_size") + 1], "1440x900")
        self.assertTrue(env["XAUTHORITY"].endswith("ceo/bot-desktop/Xauthority"))
        self.assertTrue((self.data / "active.json").exists())

    def test_start_names_missing_screen(self):
        make_profile(self.root, "ceo", "20")
        make_profile(self.root, "nova", "22", running=False)
        with self.assertRaises(NightShiftError) as e:
            self.ns().start(["ceo", "nova"])
        self.assertIn("nova", str(e.exception))

    def test_no_double_start_and_bad_fps(self):
        make_profile(self.root, "ceo", "20")
        n = self.ns()
        with self.assertRaises(NightShiftError):
            n.start(fps=99)
        n.start()
        with self.assertRaises(NightShiftError):
            n.start()

    def test_stop_without_start(self):
        with self.assertRaises(NightShiftError):
            self.ns().stop()

    def test_stop_builds_grid_video_and_report(self):
        homes = {p: make_profile(self.root, p, d, motion=m) for p, d, m in
                 (("ceo", "20", "magnetic"), ("sanju", "21", "comet_swoop"), ("nova", "22", "spring_settle"))}
        n = self.ns()
        start = n.start(label="test shift")
        run_dir = Path(start["folder"])
        for p in homes:
            (run_dir / f"{p}.mp4").write_bytes(b"x" * 10)
        now = time.time()
        seed_db(homes["ceo"], [("s1", "user", "go", None, now - 1), ("s1", "tool", "ok", "computer_use", now),
                               ("s1", "tool", "ok", "computer_use", now), ("s1", "assistant", "✅ Done, opened Thunar.", None, now)])
        seed_db(homes["sanju"], [("s2", "tool", '{"error":"human_has_control"}', "computer_use", now),
                                 ("s2", "assistant", "✋ Need you to log in.", None, now)], iso=True)
        # nova: no state.db at all
        out = n.stop(speed=10)
        self.assertTrue(all(p.poll() is not None for p in self.spawn.procs), "recorders were not stopped")
        self.assertFalse((self.data / "active.json").exists())
        cmd = self.run.calls[-1]
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn(f"layout={GRID[3][1]}", graph)
        self.assertIn("setpts=PTS/10", graph)
        self.assertIn("cursor comet_swoop", graph)
        self.assertEqual(out["video"], str(run_dir / "nightshift.mp4"))
        by = {r["profile"]: r for r in out["bots"]}
        self.assertEqual((by["ceo"]["actions"], by["ceo"]["status"], by["ceo"]["interventions"]), (2, "done", 0))
        self.assertEqual((by["sanju"]["status"], by["sanju"]["interventions"]), ("needs you", 1))
        self.assertEqual(by["nova"]["status"], "no activity")
        self.assertIn("| Ceo — Bot | magnetic | 1 | 2 | done | 0 |", out["markdown"])
        self.assertIn("Humans stepped in 1 time(s)", out["markdown"])
        self.assertTrue((run_dir / "report.md").exists())
        self.assertEqual(json.loads((run_dir / "run.json").read_text())["label"], "test shift")

    def test_video_failure_is_reported_not_raised(self):
        make_profile(self.root, "ceo", "20")
        self.run = FakeRun(rc=1)
        n = self.ns()
        run_dir = Path(n.start()["folder"])
        (run_dir / "ceo.mp4").write_bytes(b"x")
        out = n.stop()
        self.assertIsNone(out["video"])
        self.assertTrue((run_dir / "video.error.log").exists())

    def test_single_bot_video_has_no_xstack(self):
        make_profile(self.root, "ceo", "20")
        n = self.ns()
        run_dir = Path(n.start()["folder"])
        (run_dir / "ceo.mp4").write_bytes(b"x")
        n.stop()
        graph = self.run.calls[-1][self.run.calls[-1].index("-filter_complex") + 1]
        self.assertNotIn("xstack", graph)
        self.assertIn("[out]", graph)

    def test_status_and_report(self):
        make_profile(self.root, "ceo", "20")
        n = self.ns()
        self.assertFalse(n.status()["recording"])
        n.start()
        st = n.status()
        self.assertTrue(st["recording"] and st["bots"]["ceo"]["alive"])


class Facts(unittest.TestCase):
    def test_missing_or_odd_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(session_facts(Path(tmp) / "none.db", 0, 1)["status"], "no activity")
            c = sqlite3.connect(Path(tmp) / "odd.db"); c.execute("create table messages(x)"); c.close()
            self.assertEqual(session_facts(Path(tmp) / "odd.db", 0, 1)["sessions"], 0)


if __name__ == "__main__":
    unittest.main()
