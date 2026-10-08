import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nightshift import NightShift  # noqa: E402
from test_nightshift import FakeRun, FakeSpawn, make_profile  # noqa: E402
import wall  # noqa: E402


class Jpegs(unittest.TestCase):
    def test_splits_frames_across_chunks(self):
        f1, f2 = b"\xff\xd8AAAA\xff\xd9", b"\xff\xd8BBBBBBBB\xff\xd9"
        stream = io.BytesIO(b"junk" + f1 + f2[:5] + b"" + f2[5:] + b"tail")
        frames = list(wall.iter_jpegs(stream, chunk_size=7))
        self.assertEqual(frames, [f1, f2])

    def test_stream_command(self):
        cmd = wall.ffmpeg_stream_command(":21", "1440x900", 960, 5)
        self.assertEqual(cmd[cmd.index("-i") + 1], ":21")
        self.assertIn("mjpeg", cmd)
        self.assertEqual(cmd[-1], "pipe:1")


class Page(unittest.TestCase):
    def test_tiles_and_escaping(self):
        html = wall.render_page([{"profile": "ceo", "display_name": "Sanvith <CoS>", "motion": "magnetic", "running": True},
                                 {"profile": "nova", "display_name": "Nova", "motion": "spring_settle", "running": False}])
        self.assertIn('src="/stream/ceo"', html)
        self.assertIn("Sanvith &lt;CoS&gt;", html)
        self.assertIn('class="dot off"', html)
        self.assertIn("cursor spring_settle", html)

    def test_empty(self):
        self.assertIn("No Bot Screen is running", wall.render_page([]))


class WallAndDispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "hermes"
        self.data = Path(self.tmp.name) / "data"
        self.spawn = FakeSpawn()
        make_profile(self.root, "ceo", "20", motion="magnetic")
        make_profile(self.root, "sanju", "21", motion="comet_swoop")
        make_profile(self.root, "nova", "22", running=False)
        self.ns = NightShift(self.data, self.root, spawn=self.spawn, run=FakeRun())

    def tearDown(self):
        self.spawn.cleanup()
        self.tmp.cleanup()

    def test_wall_spawns_server_and_reports_url(self):
        out = self.ns.wall("open", 8799)
        cmd, _ = self.spawn.calls[0]
        self.assertTrue(cmd[1].endswith("wall.py"))
        self.assertEqual(cmd[cmd.index("--port") + 1], "8799")
        self.assertEqual(out["url"], "http://127.0.0.1:8799/")
        self.assertEqual(out["screens"], ["ceo", "sanju"])

    def test_wall_status_and_stop_without_server(self):
        self.assertFalse(self.ns.wall("status")["running"])
        self.assertFalse(self.ns.wall("stop")["running"])


if __name__ == "__main__":
    unittest.main()
