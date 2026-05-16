"""
Frame extraction via FFmpeg.
Extracts 1 frame per second + scene-change frames from a video file.
Returns a list of (ts_ms, local_path) tuples for all extracted frames.
Caller is responsible for deleting the work directory.
"""
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FFMPEG_SCALE = "scale='min(1280,iw)':-2"
FFMPEG_QUALITY = "3"   # JPEG quality (1=best, 31=worst; 3 is high quality)
SCENE_THRESHOLD = "0.4"  # scene-change sensitivity (0.0–1.0)


@dataclass
class ExtractedFrame:
    ts_ms: int
    path: Path


def extract_frames(video_path: Path, work_dir: Path) -> list[ExtractedFrame]:
    """
    Run FFmpeg to extract 1-fps + scene-change frames.
    Returns list of ExtractedFrame sorted by ts_ms.
    """
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Two-pass approach:
    # Pass 1: extract 1-fps frames (reliably gives us uniform coverage)
    # Pass 2: extract scene-change frames (catches cuts missed by 1-fps sampling)
    _extract_fps_frames(video_path, frames_dir)
    _extract_scene_change_frames(video_path, frames_dir)

    # Parse all frame files and deduplicate by ts_ms (keep first)
    frames = _parse_frame_files(frames_dir)
    logger.info("Extracted %d frames from %s", len(frames), video_path.name)
    return frames


def _extract_fps_frames(video_path: Path, out_dir: Path) -> None:
    """Extract frames at exactly 1 fps. Output: fps_{ts_ms}.jpg"""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"fps=1,{FFMPEG_SCALE}",
        "-q:v", FFMPEG_QUALITY,
        "-frame_pts", "1",
        str(out_dir / "fps_%06d.jpg"),
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning("FFmpeg fps extraction stderr: %s", result.stderr[-500:])


def _extract_scene_change_frames(video_path: Path, out_dir: Path) -> None:
    """Extract frames at scene-change points."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})',{FFMPEG_SCALE}",
        "-vsync", "vfr",
        "-q:v", FFMPEG_QUALITY,
        "-frame_pts", "1",
        str(out_dir / "scene_%08d.jpg"),
        "-y",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    # Scene frames may not exist if no scene changes detected — that's fine
    if result.returncode != 0:
        logger.debug("Scene-change extraction stderr: %s", result.stderr[-300:])


def _parse_frame_files(frames_dir: Path) -> list[ExtractedFrame]:
    """
    Parse frame files. fps_{N}.jpg → ts_ms = (N-1) * 1000.
    scene_{N}.jpg → ts_ms from the frame pts embedded in filename index.
    Deduplicates by ts_ms (1-fps frames take priority; scene frames fill gaps).
    """
    seen: dict[int, Path] = {}

    for f in sorted(frames_dir.iterdir()):
        if not f.suffix == ".jpg":
            continue
        name = f.stem
        if name.startswith("fps_"):
            # fps_000001.jpg → frame index 1 → ts_ms = (1-1)*1000 = 0
            try:
                idx = int(name.split("_", 1)[1])
                ts_ms = (idx - 1) * 1000
            except ValueError:
                continue
            if ts_ms not in seen:
                seen[ts_ms] = f
        elif name.startswith("scene_"):
            # scene frames: use index as approximate ts (imprecise but acceptable)
            # For v1, we just mark them as interstitial; exact ts can be improved later
            try:
                idx = int(name.split("_", 1)[1])
                # Scene frame ts: we don't have pts here without showinfo filter.
                # Use a sentinel gap value so they slot between fps frames.
                # For now, skip scene frames that collide with fps frames.
                # (Future improvement: use ffprobe showinfo to get exact pts_time)
                ts_ms = idx * 1000 - 500  # approximate midpoint heuristic
                ts_ms = max(0, ts_ms)
            except ValueError:
                continue
            if ts_ms not in seen:
                seen[ts_ms] = f

    return sorted(
        [ExtractedFrame(ts_ms=ts, path=path) for ts, path in seen.items()],
        key=lambda x: x.ts_ms,
    )


def probe_video_metadata(video_path: Path) -> dict:
    """Return duration, width, height, fps from ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration",
        "-of", "default=noprint_wrappers=1:nokey=0",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    meta: dict = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            meta[k.strip()] = v.strip()

    width = int(meta.get("width", 0)) or None
    height = int(meta.get("height", 0)) or None
    duration = float(meta.get("duration", 0)) or None
    fps_raw = meta.get("r_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = round(int(num) / int(den), 3) if int(den) else None
    except (ValueError, ZeroDivisionError):
        fps = None

    return {"duration_sec": duration, "width": width, "height": height, "fps": fps}
