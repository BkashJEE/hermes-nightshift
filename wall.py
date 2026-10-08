"""Bot Wall: one local web page that shows every Bot Screen live, side by side, with the Bot's name,
cursor style and its latest words. Runs as its own small process (``python -m nightshift.wall`` or
``python wall.py``) so it outlives the tool call that started it. Binds to loopback only.

Each tile is an MJPEG stream straight out of ``ffmpeg x11grab`` on that Bot's X display; one ffmpeg per
open tile, killed when the viewer goes away. The page is static HTML plus a 3-second status poll.
"""

import argparse
import html
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SOI, EOI = b"\xff\xd8", b"\xff\xd9"
BOUNDARY = b"--botwall"


def iter_jpegs(stream, chunk_size: int = 65536):
    """Split a raw MJPEG byte stream into complete JPEG frames."""
    buf = b""
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            return
        buf += chunk
        while True:
            start = buf.find(SOI)
            if start < 0:
                buf = b""
                break
            end = buf.find(EOI, start + 2)
            if end < 0:
                buf = buf[start:]
                break
            yield buf[start:end + 2]
            buf = buf[end + 2:]


def ffmpeg_stream_command(display: str, geometry: str, width: int, fps: float, ffmpeg: str = "ffmpeg") -> list:
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "x11grab", "-framerate", str(fps),
            "-video_size", geometry, "-i", display, "-vf", f"scale={width}:-2", "-q:v", "6", "-f", "mjpeg", "pipe:1"]


def last_words(home: Path) -> str:
    """The Bot's newest reply, from its state.db (read-only); empty when there is none."""
    db = home / "state.db"
    if not db.exists():
        return ""
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        row = c.execute("select content from messages where role='assistant' and coalesce(content,'')<>'' "
                        "order by rowid desc limit 1").fetchone()
    except sqlite3.Error:
        return ""
    return re.sub(r"\s+", " ", (row[0] if row else "")).strip()[:240]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Bot Wall</title>
<style>
:root{color-scheme:dark}body{margin:0;background:#0b0d12;color:#e6e8ef;font:14px/1.4 Inter,system-ui,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid #1d2230}
header h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.02em}
header .rec{margin-left:auto;font-family:ui-monospace,monospace;font-size:12px;color:#9aa3b5}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(460px,1fr));gap:12px;padding:12px}
.tile{background:#121622;border:1px solid #1d2230;border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.tile img{width:100%;aspect-ratio:16/10;object-fit:contain;background:#000;display:block}
.bar{display:flex;align-items:center;gap:10px;padding:8px 12px}
.name{font-weight:600}.motion{font-family:ui-monospace,monospace;font-size:12px;color:#8fd3ff;background:#0f2a3a;padding:2px 8px;border-radius:999px}
.dot{width:8px;height:8px;border-radius:50%;background:#3dd68c;box-shadow:0 0 8px #3dd68c88}.dot.off{background:#6b7280;box-shadow:none}
.words{padding:0 12px 10px;color:#aab3c5;font-size:13px;min-height:2.6em}
</style></head><body><header><h1>Bot Wall</h1><span id="rec" class="rec"></span></header><main id="wall">__TILES__</main>
<script>
async function poll(){try{const r=await fetch('/status.json');const s=await r.json();
document.getElementById('rec').textContent=(s.recording?'● REC '+s.run:'not recording')+' · '+new Date().toLocaleTimeString();
for(const b of s.bots){const w=document.getElementById('w-'+b.profile);if(w)w.textContent=b.words||'…';
const d=document.getElementById('d-'+b.profile);if(d)d.className='dot'+(b.running?'':' off');}}catch(e){}}
poll();setInterval(poll,3000);
</script></body></html>"""


def render_page(bots: list) -> str:
    tiles = []
    for b in bots:
        p = html.escape(b["profile"])
        tiles.append(
            f'<section class="tile"><img src="/stream/{p}" alt="{html.escape(b["display_name"])}">'
            f'<div class="bar"><span id="d-{p}" class="dot{"" if b["running"] else " off"}"></span>'
            f'<span class="name">{html.escape(b["display_name"])}</span>'
            f'<span class="motion">cursor {html.escape(b["motion"])}</span></div>'
            f'<div id="w-{p}" class="words">…</div></section>')
    return PAGE.replace("__TILES__", "".join(tiles) or '<p style="padding:16px">No Bot Screen is running.</p>')


class Wall:
    def __init__(self, root: Path, data: Path, width: int = 960, fps: float = 5.0, ffmpeg: str = "ffmpeg"):
        self.root, self.data, self.width, self.fps, self.ffmpeg = Path(root), Path(data), width, fps, ffmpeg

    def bots(self) -> list:
        from nightshift import bots  # local import keeps `python wall.py` runnable on its own
        return [b for b in bots(self.root) if b["running"]]

    def status(self) -> dict:
        active = None
        try:
            active = json.loads((self.data / "active.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        return {"recording": bool(active), "run": (active or {}).get("id"),
                "bots": [{"profile": b["profile"], "running": b["running"], "words": last_words(Path(b["home"]))}
                         for b in self.bots()]}


def make_handler(wall: Wall):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, render_page(wall.bots()).encode("utf-8"), "text/html; charset=utf-8")
            if self.path == "/status.json":
                return self._send(200, json.dumps(wall.status()).encode("utf-8"), "application/json")
            m = re.fullmatch(r"/stream/([A-Za-z0-9_-]+)", self.path)
            if m:
                return self._stream(m.group(1))
            self._send(404, b"not found", "text/plain")

        def _stream(self, profile: str):
            bot = next((b for b in wall.bots() if b["profile"] == profile), None)
            if not bot:
                return self._send(404, b"no running screen for that profile", "text/plain")
            cmd = ffmpeg_stream_command(bot["display"], bot["geometry"], wall.width, wall.fps, wall.ffmpeg)
            env = {**os.environ, "DISPLAY": bot["display"], "XAUTHORITY": bot["xauthority"]}
            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            self.send_response(200)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY[2:].decode()}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                for frame in iter_jpegs(proc.stdout):
                    self.wfile.write(BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                     str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                proc.kill()
                proc.wait()
    return Handler


def serve(root: Path, data: Path, port: int, width: int, fps: float) -> None:
    wall = Wall(root, data, width, fps)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(wall))
    server.daemon_threads = True
    pidfile = data / "wall.json"
    data.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(json.dumps({"pid": os.getpid(), "port": port, "url": f"http://127.0.0.1:{port}/", "started": time.time()}))

    def bye(*_):
        pidfile.unlink(missing_ok=True)
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    try:
        server.serve_forever()
    finally:
        pidfile.unlink(missing_ok=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bot Wall: every Bot Screen live on one local page")
    ap.add_argument("--root", default=None, help="Hermes root (default: the usual ~/.hermes)")
    ap.add_argument("--data", required=True, help="plugin data folder (for wall.json and active.json)")
    ap.add_argument("--port", type=int, default=8793)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--fps", type=float, default=5.0)
    a = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from nightshift import default_root
    serve(Path(a.root) if a.root else default_root(), Path(a.data), a.port, a.width, a.fps)


if __name__ == "__main__":
    main()
