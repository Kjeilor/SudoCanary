"""
core/tiles/tile_server.py

Minimal HTTP server that serves:
  GET /tiles/{z}/{x}/{y}.png  — OSM tile cache
  GET /static/{filename}       — Leaflet JS, CSS, and other static assets

Runs on a daemon thread. Starts before the main window appears.
Stopped cleanly in app closeEvent().

Port 8765 by default. Tries 8765–8775 if port is in use.
Grey placeholder PNG returned for missing tiles (generated once at startup).
All HTTP request logging suppressed.
"""
from __future__ import annotations

import io
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
# Placeholder tile — generated once at import time
# ---------------------------------------------------------------------------

def _make_grey_tile() -> bytes:
    """Return a 256×256 grey PNG tile as bytes."""
    try:
        from PIL import Image
        img = Image.new("RGB", (256, 256), color=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Minimal valid 1×1 grey PNG as fallback
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00"
            b"\x00\x00\x01\x00\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
            b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
            b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )


_GREY_TILE: bytes = _make_grey_tile()


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class _TileHandler(BaseHTTPRequestHandler):
    tile_dir:   Path
    static_dir: Path

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        # ── Static assets (Leaflet JS/CSS) ────────────────────────────────
        if path.startswith("/static/"):
            filename = path[len("/static/"):]
            file_path = self.static_dir / filename
            if file_path.exists() and file_path.is_file():
                data = file_path.read_bytes()
                ctype = (
                    "application/javascript" if filename.endswith(".js")
                    else "text/css" if filename.endswith(".css")
                    else "application/octet-stream"
                )
                self._respond(200, ctype, data)
            else:
                self._respond(404, "text/plain", b"Not found")
            return

        # ── Tiles ──────────────────────────────────────────────────────────
        if path.startswith("/tiles/"):
            parts = path[len("/tiles/"):].strip("/").split("/")
            if len(parts) == 3:
                z, x, y_png = parts
                y = y_png.replace(".png", "")
                tile_path = self.tile_dir / z / x / f"{y}.png"
                if tile_path.exists():
                    self._respond(200, "image/png", tile_path.read_bytes())
                else:
                    self._respond(200, "image/png", _GREY_TILE)
            else:
                self._respond(400, "text/plain", b"Bad tile path")
            return

        self._respond(404, "text/plain", b"Not found")

    def _respond(self, code: int, ctype: str, data: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args) -> None:  # suppress all HTTP logs
        pass


# ---------------------------------------------------------------------------
# TileServer
# ---------------------------------------------------------------------------

class TileServer:
    """
    Embedded HTTP server for offline map tiles and static Leaflet assets.
    Call start() once at app launch; stop() on closeEvent().
    """

    def __init__(
        self,
        tile_dir: str | Path = "tiles/osm",
        static_dir: str | Path = "tools/roadworks/static",
        port: int = 8765,
    ) -> None:
        self._tile_dir   = Path(tile_dir)
        self._static_dir = Path(static_dir)
        self._preferred_port = port
        self._server: HTTPServer | None = None
        self._port: int = port
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the server on a daemon thread. Non-blocking."""
        tile_dir   = self._tile_dir
        static_dir = self._static_dir

        class Handler(_TileHandler):
            pass

        Handler.tile_dir   = tile_dir
        Handler.static_dir = static_dir

        # Try ports 8765–8775
        for port in range(self._preferred_port, self._preferred_port + 10):
            try:
                server = HTTPServer(("localhost", port), Handler)
                self._server = server
                self._port   = port
                break
            except OSError:
                continue

        if self._server is None:
            print("[TileServer] Could not bind to any port. Map will be offline.")
            return

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="TileServer",
        )
        self._thread.start()
        print(f"[TileServer] Running on port {self._port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None

    def url(self) -> str:
        return f"http://localhost:{self._port}"

    @property
    def port(self) -> int:
        return self._port

    def verify_cache(
        self,
        zoom_levels: list,
        bounds: dict,
    ) -> dict:
        """
        Check what percentage of tiles for the given bounds/zoom levels
        are present in the local cache.
        bounds: {"west", "south", "east", "north"}
        Returns: {"total", "cached", "pct", "missing"}
        """
        import math

        def _deg_to_tile(lat, lon, z):
            lat_r = math.radians(lat)
            n = 2 ** z
            x = int((lon + 180.0) / 360.0 * n)
            y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
            return x, y

        total = 0
        cached = 0
        missing = []

        west  = bounds.get("west",  32.4)
        south = bounds.get("south", 0.1)
        east  = bounds.get("east",  32.8)
        north = bounds.get("north", 0.5)

        for z in zoom_levels:
            x_min, y_max = _deg_to_tile(north, west, z)
            x_max, y_min = _deg_to_tile(south, east, z)
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    total += 1
                    tile_path = self._tile_dir / str(z) / str(x) / f"{y}.png"
                    if tile_path.exists():
                        cached += 1
                    else:
                        missing.append(f"{z}/{x}/{y}")

        pct = (cached / total * 100) if total > 0 else 0
        return {"total": total, "cached": cached, "pct": round(pct, 1), "missing": missing[:20]}


# Module-level singleton — started in main()
tile_server = TileServer()