import json
import os
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


SYSTEM_LIBCUDA_CANDIDATES = (
    "/lib/x86_64-linux-gnu/libcuda.so.1",
    "/usr/lib/x86_64-linux-gnu/libcuda.so.1",
)


class ExportTask:
    def __init__(
        self,
        input_path,
        output_dir,
        pos,
        mount_id,
        seq_id,
        capture_time,
        exporter_path,
        task_id=None,
        model_root=None,
        output_size="3840x1920",
        stitch_type="optflow",
        enable_flowstate=True,
        enable_denoise=True,
        enable_direction_lock=False,
        disable_cuda=False,
        image_processing_accel="auto",
        timeout_seconds=21600,
        extra_args=None,
    ):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.pos = pos
        self.mount_id = mount_id
        self.seq_id = seq_id
        self.capture_time = capture_time
        self.exporter_path = exporter_path
        self.task_id = task_id or _default_task_id(capture_time, mount_id, seq_id, pos)
        self.model_root = model_root
        self.output_size = output_size
        self.stitch_type = stitch_type
        self.enable_direction_lock = enable_direction_lock
        self.enable_flowstate = True if enable_direction_lock else enable_flowstate
        self.enable_denoise = enable_denoise
        self.disable_cuda = disable_cuda
        self.image_processing_accel = image_processing_accel
        self.timeout_seconds = timeout_seconds
        self.extra_args = list(extra_args or [])

    def __repr__(self):
        return (
            "ExportTask(input_path=%r, pos=%r, mount_id=%r, seq_id=%r, task_id=%r)"
            % (str(self.input_path), self.pos, self.mount_id, self.seq_id, self.task_id)
        )


class ExportResult:
    def __init__(
        self,
        task,
        output_path,
        log_path,
        command,
        status,
        returncode,
        start,
        end,
    ):
        self.task = task
        self.output_path = Path(output_path)
        self.log_path = Path(log_path)
        self.command = list(command)
        self.status = status
        self.returncode = returncode
        self.start = start
        self.end = end

    def to_manifest_row(self):
        return {
            "input": str(self.task.input_path),
            "output": str(self.output_path),
            "pos": self.task.pos,
            "mount_id": self.task.mount_id,
            "seq_id": self.task.seq_id,
            "command": self.command,
            "status": self.status,
            "returncode": self.returncode,
            "timeout_seconds": self.task.timeout_seconds,
            "output_size": self.task.output_size,
            "enable_flowstate": self.task.enable_flowstate,
            "enable_denoise": self.task.enable_denoise,
            "enable_direction_lock": self.task.enable_direction_lock,
            "start": self.start,
            "end": self.end,
            "log_path": str(self.log_path),
        }

    def __repr__(self):
        return (
            "ExportResult(status=%r, returncode=%r, output_path=%r)"
            % (self.status, self.returncode, str(self.output_path))
        )


def build_output_path(task):
    capture_time = _ensure_datetime(task.capture_time)
    filename = "%s_%s_%s.mp4" % (
        capture_time.strftime("%Y%m%d_%H%M%S"),
        _safe_filename_part(task.mount_id),
        _safe_filename_part(task.seq_id),
    )
    return task.output_dir / task.pos / filename


def build_export_command(task, output_path=None, log_path=None):
    output_path = Path(output_path) if output_path is not None else build_output_path(task)
    log_path = Path(log_path) if log_path is not None else _build_log_path(task)

    if isinstance(task.exporter_path, (list, tuple)):
        command = [str(part) for part in task.exporter_path]
    else:
        command = [str(task.exporter_path)]

    command.extend(
        [
            "--input",
            str(task.input_path),
            "--output",
            str(output_path),
        ]
    )

    if task.model_root:
        command.extend(["--model-root", str(task.model_root)])

    if task.output_size:
        command.extend(["--output-size", str(task.output_size)])

    if task.stitch_type:
        command.extend(["--stitch-type", str(task.stitch_type)])

    if task.enable_flowstate:
        command.append("--enable-flowstate")

    if task.enable_denoise:
        command.append("--enable-denoise")

    if task.enable_direction_lock:
        command.append("--enable-directionlock")

    if task.disable_cuda:
        command.append("--disable-cuda")

    if task.image_processing_accel:
        command.extend(["--image-processing-accel", str(task.image_processing_accel)])

    if task.timeout_seconds:
        command.extend(["--timeout-seconds", str(task.timeout_seconds)])

    command.extend(["--log-path", str(log_path)])
    command.extend(str(arg) for arg in task.extra_args)
    return command


def build_export_env(base_env=None, system_libcuda_candidates=None):
    env = dict(os.environ if base_env is None else base_env)
    candidates = system_libcuda_candidates or SYSTEM_LIBCUDA_CANDIDATES
    for candidate in candidates:
        path = Path(candidate)
        if not path.exists():
            continue
        existing = env.get("LD_PRELOAD", "").strip()
        existing_parts = existing.split() if existing else []
        if str(path) in existing_parts:
            return env
        env["LD_PRELOAD"] = " ".join([str(path)] + existing_parts)
        return env
    return env


def run_export_task(task, overwrite=False, manifest_path=None, manifest_lock=None):
    output_path = build_output_path(task)
    log_path = _build_log_path(task)
    manifest_path = Path(manifest_path) if manifest_path is not None else _build_manifest_path(task)
    command = build_export_command(task, output_path, log_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    start = _now_iso()
    if output_path.exists() and not overwrite:
        end = _now_iso()
        result = ExportResult(
            task=task,
            output_path=output_path,
            log_path=log_path,
            command=command,
            status="skipped",
            returncode=None,
            start=start,
            end=end,
        )
        _write_log(log_path, command, result.status, result.returncode, start, end)
        _append_manifest(manifest_path, result, manifest_lock)
        return result

    stdout = ""
    stderr = ""
    error_message = None
    returncode = None
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=task.timeout_seconds,
            env=build_export_env(),
        )
        stdout = completed.stdout
        stderr = completed.stderr
        returncode = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_process_text(exc.stdout)
        stderr = _coerce_process_text(exc.stderr)
        error_message = "%s: exporter exceeded %s seconds" % (
            exc.__class__.__name__,
            task.timeout_seconds,
        )
        returncode = 124
    except OSError as exc:
        error_message = "%s: %s" % (exc.__class__.__name__, exc)

    end = _now_iso()
    status = "done" if returncode == 0 else "failed"
    result = ExportResult(
        task=task,
        output_path=output_path,
        log_path=log_path,
        command=command,
        status=status,
        returncode=returncode,
        start=start,
        end=end,
    )
    _write_log(log_path, command, status, returncode, start, end, stdout, stderr, error_message)
    _append_manifest(manifest_path, result, manifest_lock)
    return result


def run_export_queue(tasks, max_parallel_exports=1, overwrite=False, on_result=None):
    if max_parallel_exports < 1:
        raise ValueError("max_parallel_exports must be >= 1")

    task_list = list(tasks)
    if not task_list:
        return []

    manifest_lock = threading.Lock()
    results = [None] * len(task_list)

    with ThreadPoolExecutor(max_workers=max_parallel_exports) as executor:
        futures = {
            executor.submit(run_export_task, task, overwrite, None, manifest_lock): index
            for index, task in enumerate(task_list)
        }
        for future in as_completed(futures):
            index = futures[future]
            result = future.result()
            results[index] = result
            if on_result is not None:
                on_result(result)

    return results


def _build_manifest_path(task):
    return task.output_dir / "export_manifest.jsonl"


def _build_log_path(task):
    return (
        task.output_dir
        / "export_logs"
        / ("%s.log" % _safe_filename_part(task.task_id))
    )


def _append_manifest(manifest_path, result, manifest_lock=None):
    row = result.to_manifest_row()

    def write_row():
        with Path(manifest_path).open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, sort_keys=True) + "\n")

    if manifest_lock is None:
        write_row()
    else:
        with manifest_lock:
            write_row()


def _write_log(log_path, command, status, returncode, start, end, stdout="", stderr="", error_message=None):
    with Path(log_path).open("a", encoding="utf-8") as file:
        file.write("command: %s\n" % shlex.join(command))
        file.write("status: %s\n" % status)
        file.write("returncode: %s\n" % returncode)
        file.write("start: %s\n" % start)
        file.write("end: %s\n" % end)
        if error_message:
            file.write("\n[error]\n%s\n" % error_message)
        if stdout:
            file.write("\n[stdout]\n%s" % stdout)
            if not stdout.endswith("\n"):
                file.write("\n")
        if stderr:
            file.write("\n[stderr]\n%s" % stderr)
            if not stderr.endswith("\n"):
                file.write("\n")


def _coerce_process_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _default_task_id(capture_time, mount_id, seq_id, pos):
    return "%s_%s_%s_%s" % (
        _ensure_datetime(capture_time).strftime("%Y%m%d_%H%M%S"),
        _safe_filename_part(mount_id),
        _safe_filename_part(seq_id),
        _safe_filename_part(pos),
    )


def _safe_filename_part(value):
    text = str(value)
    text = text.replace(os.sep, "_")
    if os.altsep:
        text = text.replace(os.altsep, "_")
    return text


def _ensure_datetime(value):
    if not isinstance(value, datetime):
        raise TypeError("capture_time must be datetime, got %s" % value.__class__.__name__)
    return value


def _now_iso():
    return datetime.now(timezone.utc).isoformat()
