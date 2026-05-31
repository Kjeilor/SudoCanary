#!/usr/bin/env python3
"""
tools/_tile_downloader.py

Downloads OSM tiles for a bounding box and saves them to tiles/osm/{z}/{x}/{y}.png.
Run once before the showcase to populate the offline tile cache.

Usage:
    python3 tools/_tile_downloader.py \\
        --west 32.4 --south 0.1 --east 32.8 --north 0.5 \\
        --zoom-min 10 --zoom-max 16 \\
        --output tiles/osm/

Defaults match the Kampala demo corridor.

OSM Tile Usage Policy:
  - 0.5-second delay between requests
  - Identifies itself with a descriptive User-Agent
  - Only downloads tiles not already cached
"""
from __future__ import annotations

import argparse
import math
import os
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests not installed. Run: pip install requests")
    raise


OSM_TEMPLATE   = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
USER_AGENT     = "SudoCanary-Prototype/1.0 (showcase demo; contact: admin@ateker.io)"
REQUEST_DELAY  = 0.5  # seconds between requests — OSM policy


def deg_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """Convert lat/lon to tile coordinates (x, y) at given zoom."""
    lat_r = math.radians(lat)
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tiles_for_bbox(
    west: float, south: float, east: float, north: float, zoom: int
) -> list[tuple[int, int, int]]:
    x_min, y_min = deg_to_tile(north, west, zoom)
    x_max, y_max = deg_to_tile(south, east, zoom)
    # Ensure correct order
    if x_min > x_max:
        x_min, x_max = x_max, x_min
    if y_min > y_max:
        y_min, y_max = y_max, y_min
    tiles = []
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            tiles.append((zoom, x, y))
    return tiles


def download_tiles(
    west: float,
    south: float,
    east: float,
    north: float,
    zoom_min: int,
    zoom_max: int,
    output_dir: str,
) -> None:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    out = Path(output_dir)
    total = 0
    downloaded = 0
    skipped = 0
    failed = 0

    for zoom in range(zoom_min, zoom_max + 1):
        tiles = tiles_for_bbox(west, south, east, north, zoom)
        total += len(tiles)
        print(f"Zoom {zoom}: {len(tiles)} tiles")

        for z, x, y in tiles:
            tile_path = out / str(z) / str(x) / f"{y}.png"
            if tile_path.exists():
                skipped += 1
                continue

            tile_path.parent.mkdir(parents=True, exist_ok=True)
            url = OSM_TEMPLATE.format(z=z, x=x, y=y)

            try:
                resp = session.get(url, timeout=10)
                if resp.status_code == 200:
                    tile_path.write_bytes(resp.content)
                    downloaded += 1
                    print(f"  ✓ {z}/{x}/{y}")
                else:
                    failed += 1
                    print(f"  ✗ {z}/{x}/{y} — HTTP {resp.status_code}")
                time.sleep(REQUEST_DELAY)
            except Exception as exc:
                failed += 1
                print(f"  ✗ {z}/{x}/{y} — {exc}")

    print(f"\nDone. {total} total, {downloaded} downloaded, {skipped} skipped, {failed} failed.")
    print(f"Tiles saved to: {out.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download OSM tiles for offline use."
    )
    parser.add_argument("--west",     type=float, default=32.4,  help="West longitude")
    parser.add_argument("--south",    type=float, default=0.1,   help="South latitude")
    parser.add_argument("--east",     type=float, default=32.8,  help="East longitude")
    parser.add_argument("--north",    type=float, default=0.5,   help="North latitude")
    parser.add_argument("--zoom-min", type=int,   default=10,    help="Minimum zoom level")
    parser.add_argument("--zoom-max", type=int,   default=16,    help="Maximum zoom level")
    parser.add_argument("--output",   type=str,   default="tiles/osm/",
                        help="Output directory (default: tiles/osm/)")
    args = parser.parse_args()

    if args.zoom_max > 17:
        print("Warning: zoom > 17 will download very many tiles. Capping at 17.")
        args.zoom_max = 17

    print(f"Downloading tiles: [{args.south},{args.west}] to [{args.north},{args.east}]")
    print(f"Zoom range: {args.zoom_min}–{args.zoom_max}")
    print(f"Output: {args.output}")
    print(f"Delay: {REQUEST_DELAY}s between requests\n")

    download_tiles(
        west=args.west, south=args.south,
        east=args.east, north=args.north,
        zoom_min=args.zoom_min, zoom_max=args.zoom_max,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()