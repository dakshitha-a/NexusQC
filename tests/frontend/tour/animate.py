"""Turn a recorded scene into one of the README's animations.

Ported from NextTex's `e2e/shots/animate.py` on 2026-10-22, unchanged in
what it does.  `tests/frontend/tour/recorder.mjs` leaves a directory per
scene: every repaint of the window at full resolution, with the time it painted, and the marks the
scene made, "look here" and "pull back", and the waits it asked to have
played back quickly.  This file is the camera.  It samples the scene at a
steady rate, glides a crop rectangle between the marks with an ease in and
out, crops each full frame at that rectangle and scales it to the output's
width, so a zoomed view is cut from the real pixels rather than blown up
from a small copy.

The output is an animated WebP, which plays and loops like a GIF in any
current browser and in a README.  NextTex filmed GIFs first and moved off
them: 256 colours banded the interface's quiet greys, and the weight held
the animations to ten frames a second at 640 pixels.  WebP keeps full
colour and stores only what changed between frames.

    python3 tests/frontend/tour/animate.py SCENE_DIR OUT.webp [--width 1280] [--fps 25] [--quality 75]
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_right
from pathlib import Path

from PIL import Image

# The closest the camera comes: never more than this many times the whole
# window, so a zoom shows a region with its surroundings, not one word.
MAX_ZOOM = 2.6


def ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return 4 * u * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def fit(rect: dict, view: dict, zoom: float = MAX_ZOOM) -> tuple[float, float, float, float]:
    """The mark's rectangle grown to the output's shape, kept on screen.

    `zoom` is the mark's own limit when it gives one: a close-up of the
    typeset page needs to come nearer than the window's usual 2.6 for its
    type to be read, and the frames are filmed at twice the pixels or more
    so that nearer view is still cut from real pixels."""
    vw, vh = view["width"], view["height"]
    aspect = vw / vh
    x, y, w, h = rect["x"], rect["y"], rect["width"], rect["height"]
    cx, cy = x + w / 2, y + h / 2
    w = max(w, h * aspect, vw / zoom)
    h = w / aspect
    if w > vw:
        w, h = vw, vh
    x = min(max(cx - w / 2, 0), vw - w)
    y = min(max(cy - h / 2, 0), vh - h)
    return (x, y, w, h)


def camera(scene: dict):
    view = scene["viewport"]
    whole = (0.0, 0.0, float(view["width"]), float(view["height"]))
    moves: list[tuple[float, float, tuple, tuple]] = []

    def at(t: float) -> tuple[float, float, float, float]:
        rect = whole
        for start, length, src, dst in moves:
            if t < start:
                break
            k = ease((t - start) / length) if length > 0 else 1.0
            rect = tuple(a + (b - a) * k for a, b in zip(src, dst))
        return rect

    # Each move starts from where the camera is at that moment, so a mark
    # that arrives before the last move has ended turns the camera from
    # where it is rather than jumping it to where it was going.
    for mark in sorted(scene["marks"], key=lambda m: m["t"]):
        target = whole if mark["kind"] == "wide" else fit(mark["rect"], view, mark.get("zoom", MAX_ZOOM))
        moves.append((mark["t"], mark["ease"], at(mark["t"]), target))

    return at


def render(scene_dir: Path, out: Path, width: int, fps: int, trim: float, tail: float, quality: int) -> None:
    scene = json.loads((scene_dir / "scene.json").read_text())
    frames = scene["frames"]
    if not frames:
        raise SystemExit(f"{scene_dir}: no frames were recorded")
    times = [f["t"] for f in frames]
    view = scene["viewport"]
    height = round(width * view["height"] / view["width"])
    at = camera(scene)
    end = scene["end"]

    cache: dict[str, Image.Image] = {}

    def frame_at(t: float) -> Image.Image:
        i = max(0, bisect_right(times, t) - 1)
        name = frames[i]["file"]
        if name not in cache:
            cache.clear()
            cache[name] = Image.open(scene_dir / name).convert("RGB")
        return cache[name]

    fast = scene.get("fast", [])

    def speed_at(t: float) -> float:
        return next((f["speed"] for f in fast if f["from"] <= t < f["to"]), 1.0)

    # Every sample is a frame: WebP keeps full colour and stores only what
    # changed between frames, so the camera can glide at the full rate.
    shots: list[Image.Image] = []
    step = 1 / fps
    t = trim
    while t <= end:
        full = frame_at(t)
        sx = full.width / view["width"]
        x, y, w, h = at(t)
        box = (round(x * sx), round(y * sx), round((x + w) * sx), round((y + h) * sx))
        shots.append(full.crop(box).resize((width, height), Image.LANCZOS))
        t += step * speed_at(t)

    # Identical neighbours become one frame held longer.
    out_frames: list[Image.Image] = []
    durations: list[int] = []
    last = None
    for im in shots:
        raw = im.tobytes()
        if raw == last:
            durations[-1] += round(1000 / fps)
            continue
        out_frames.append(im)
        durations.append(round(1000 / fps))
        last = raw
    durations[-1] += round(tail * 1000)
    out_frames[0].save(
        out, format="WEBP", save_all=True, append_images=out_frames[1:],
        duration=durations, loop=0, quality=quality, method=4,
        allow_mixed=True, minimize_size=True,
    )
    size = out.stat().st_size / 1e6
    print(f"{out.name}: {len(out_frames)} frames, {sum(durations) / 1000:.1f} s, {size:.2f} MB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--trim", type=float, default=0.0, help="seconds to drop from the start")
    parser.add_argument("--tail", type=float, default=1.5, help="seconds to hold the last frame")
    parser.add_argument("--quality", type=int, default=75, help="WebP quality; lower is smaller")
    args = parser.parse_args()
    render(args.scene, args.out, args.width, args.fps, args.trim, args.tail, args.quality)


if __name__ == "__main__":
    main()
