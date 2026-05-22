import json
import re
import shutil
import subprocess
from collections import OrderedDict
from datetime import datetime
from fractions import Fraction
from pathlib import Path


VID_RE = re.compile(r"^VID_(\d{8})_(\d{6})_(\d{2})_(\d{3})\.insv$")


class MediaItem:
    def __init__(
        self,
        video_path,
        timestamp,
        seq_id,
        stem,
        basename,
        mount_id,
        mount_path,
        lrv_path=None,
        has_lrv=False,
        recording_label=None,
    ):
        self.video_path = Path(video_path)
        self.timestamp = timestamp
        self.seq_id = seq_id
        self.stem = stem
        self.basename = basename
        self.mount_id = mount_id
        self.mount_path = Path(mount_path)
        self.lrv_path = Path(lrv_path) if lrv_path is not None else None
        self.has_lrv = has_lrv
        self.recording_label = recording_label

    def __repr__(self):
        return (
            "MediaItem("
            "basename=%r, mount_id=%r, timestamp=%r, seq_id=%r, has_lrv=%r"
            ")"
            % (self.basename, self.mount_id, self.timestamp, self.seq_id, self.has_lrv)
        )


def parse_media_filename(path):
    video_path = Path(path)
    match = VID_RE.match(video_path.name)
    if match is None:
        raise ValueError("not an Insta360 VID .insv filename: %s" % video_path.name)

    date_part, time_part, _, seq_id = match.groups()
    timestamp = datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")
    mount_path = _infer_mount_path(video_path)

    return MediaItem(
        video_path=video_path,
        timestamp=timestamp,
        seq_id=seq_id,
        stem=video_path.stem,
        basename=video_path.name,
        mount_id=mount_path.name,
        mount_path=mount_path,
    )


def find_lrv_for_video(path):
    video_path = Path(path)
    match = VID_RE.match(video_path.name)
    if match is None:
        return None

    date_part, time_part, _, seq_id = match.groups()
    lrv_name = "LRV_%s_%s_01_%s.lrv" % (date_part, time_part, seq_id)
    lrv_path = video_path.with_name(lrv_name)
    if lrv_path.exists():
        return lrv_path
    return None


def format_video_stream_metadata(streams):
    stream_labels = OrderedDict()
    for stream in streams or []:
        label = _format_single_stream_metadata(stream)
        if not label:
            continue
        stream_labels[label] = stream_labels.get(label, 0) + 1

    labels = []
    for label, count in stream_labels.items():
        if count > 1:
            labels.append("%dx %s" % (count, label))
        else:
            labels.append(label)
    return " + ".join(labels)


def probe_video_metadata(path, timeout_seconds=3):
    if shutil.which("ffprobe") is None:
        return ""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    try:
        data = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return ""
    return format_video_stream_metadata(data.get("streams", []))


def scan_mounts(root="/media/vox", probe_metadata=False):
    root_path = Path(root)
    items_by_mount = {}
    if not root_path.exists():
        return items_by_mount

    for mount_path in sorted(path for path in root_path.iterdir() if path.is_dir()):
        camera_dir = mount_path / "DCIM" / "Camera01"
        if not camera_dir.is_dir():
            continue

        items = []
        for video_path in sorted(camera_dir.glob("VID_*.insv")):
            try:
                item = parse_media_filename(video_path)
            except ValueError:
                continue
            lrv_path = find_lrv_for_video(video_path)
            item.lrv_path = lrv_path
            item.has_lrv = lrv_path is not None
            if probe_metadata:
                item.recording_label = probe_video_metadata(video_path)
            items.append(item)

        if items:
            items_by_mount[mount_path.name] = items

    return items_by_mount


def _infer_mount_path(video_path):
    parts = video_path.parts
    if "DCIM" in parts:
        dcim_index = parts.index("DCIM")
        if dcim_index > 0:
            return Path(*parts[:dcim_index])
    return video_path.parent.parent.parent


def _format_single_stream_metadata(stream):
    if not isinstance(stream, dict):
        return ""
    try:
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    except (TypeError, ValueError):
        return ""
    if width <= 0 or height <= 0:
        return ""

    fps = _format_fps(stream.get("avg_frame_rate")) or _format_fps(
        stream.get("r_frame_rate")
    )
    if fps:
        return "%dx%d @ %sfps" % (width, height, fps)
    return "%dx%d @ unknown fps" % (width, height)


def _format_fps(rate_text):
    fps = _parse_frame_rate(rate_text)
    if fps is None:
        return ""
    rounded = round(float(fps))
    if abs(float(fps) - rounded) < 0.005:
        return str(int(rounded))
    return ("%.2f" % float(fps)).rstrip("0").rstrip(".")


def _parse_frame_rate(rate_text):
    if not rate_text:
        return None
    try:
        value = Fraction(str(rate_text))
    except (ValueError, ZeroDivisionError):
        return None
    if value <= 0:
        return None
    return value
