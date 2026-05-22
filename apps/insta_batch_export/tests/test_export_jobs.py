import json
import stat
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from apps.insta_batch_export.core.export_jobs import (
    ExportTask,
    build_export_env,
    build_export_command,
    build_output_path,
    run_export_queue,
    run_export_task,
)


class ExportJobsTest(unittest.TestCase):
    def make_task(self, tmpdir, **overrides):
        defaults = {
            "input_path": str(Path(tmpdir) / "VID_20260521_191237_00_006.insv"),
            "output_dir": str(Path(tmpdir) / "out"),
            "pos": "left_wrist",
            "mount_id": "CARD_A",
            "seq_id": "006",
            "capture_time": datetime(2026, 5, 21, 19, 12, 37),
            "exporter_path": "/fake/insta_media_exporter",
        }
        defaults.update(overrides)
        Path(defaults["input_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(defaults["input_path"]).write_text("fake input\n", encoding="utf-8")
        return ExportTask(**defaults)

    def make_fake_exporter(self, directory, sleep_seconds=0.0, exit_code=0, track_parallel=False):
        script_path = Path(directory) / "fake_exporter.py"
        active_path = Path(directory) / "active.txt"
        max_seen_path = Path(directory) / "max_seen.txt"
        lock_path = Path(directory) / "active.lock"
        script = f"""#!/usr/bin/env python3
import argparse
import fcntl
import pathlib
import sys
import time

active_path = pathlib.Path({str(active_path)!r})
max_seen_path = pathlib.Path({str(max_seen_path)!r})
lock_path = pathlib.Path({str(lock_path)!r})
track_parallel = {track_parallel!r}

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--log-path")
parser.add_argument("--model-root")
parser.add_argument("--output-size")
parser.add_argument("--stitch-type")
parser.add_argument("--image-processing-accel")
parser.add_argument("--timeout-seconds")
parser.add_argument("--enable-flowstate", action="store_true")
parser.add_argument("--enable-denoise", action="store_true")
parser.add_argument("--disable-cuda", action="store_true")
args = parser.parse_args()

def read_int(path):
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        return 0
    except ValueError:
        return 0

def write_int(path, value):
    path.write_text(str(value), encoding="utf-8")

if track_parallel:
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active = read_int(active_path) + 1
        write_int(active_path, active)
        write_int(max_seen_path, max(read_int(max_seen_path), active))
        fcntl.flock(lock, fcntl.LOCK_UN)

time.sleep({sleep_seconds!r})
pathlib.Path(args.output).parent.mkdir(parents=True, exist_ok=True)
pathlib.Path(args.output).write_text("fake mp4\\n", encoding="utf-8")
print("fake stdout " + args.input)
print("fake stderr " + args.output, file=sys.stderr)

if track_parallel:
    with lock_path.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        write_int(active_path, max(0, read_int(active_path) - 1))
        fcntl.flock(lock, fcntl.LOCK_UN)

sys.exit({exit_code!r})
"""
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR)
        return script_path, max_seen_path

    def read_manifest(self, output_dir):
        manifest_path = Path(output_dir) / "export_manifest.jsonl"
        return [
            json.loads(line)
            for line in manifest_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_build_output_path_uses_pos_timestamp_mount_and_seq_without_date_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task = self.make_task(tmpdir)
            expected = (
                Path(tmpdir)
                / "out"
                / "left_wrist"
                / "20260521_191237_CARD_A_006.mp4"
            )

            self.assertEqual(build_output_path(task), expected)

    def test_build_export_command_contains_fixed_export_options(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task = self.make_task(
                tmpdir,
                model_root="/models",
                output_size="1920x960",
                stitch_type="optflow",
                image_processing_accel="auto",
                enable_denoise=False,
                enable_direction_lock=True,
            )
            output_path = build_output_path(task)
            log_path = Path(tmpdir) / "out" / "export_logs" / "task.log"

            command = build_export_command(task, output_path, log_path)

            self.assertEqual(command[0], "/fake/insta_media_exporter")
            self.assertIn("--input", command)
            self.assertIn(str(task.input_path), command)
            self.assertIn("--output", command)
            self.assertIn(str(output_path), command)
            self.assertIn("--model-root", command)
            self.assertIn("/models", command)
            self.assertIn("--output-size", command)
            self.assertIn("1920x960", command)
            self.assertIn("--stitch-type", command)
            self.assertIn("optflow", command)
            self.assertIn("--enable-flowstate", command)
            self.assertNotIn("--enable-denoise", command)
            self.assertIn("--enable-directionlock", command)
            self.assertIn("--image-processing-accel", command)
            self.assertIn("auto", command)
            self.assertIn("--log-path", command)
            self.assertIn(str(log_path), command)

    def test_build_export_env_prepends_system_libcuda_preload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            libcuda_path = Path(tmpdir) / "libcuda.so.1"
            libcuda_path.write_text("", encoding="utf-8")

            env = build_export_env(
                base_env={"LD_PRELOAD": "/already/preloaded.so"},
                system_libcuda_candidates=[str(libcuda_path)],
            )

            self.assertEqual(
                env["LD_PRELOAD"],
                "{} /already/preloaded.so".format(libcuda_path),
            )

    def test_run_export_task_skips_existing_output_without_overwrite_and_writes_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task = self.make_task(tmpdir, task_id="skip-task")
            output_path = build_output_path(task)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("already exported\n", encoding="utf-8")

            result = run_export_task(task, overwrite=False)

            self.assertEqual(result.status, "skipped")
            self.assertIsNone(result.returncode)
            self.assertEqual(result.output_path, output_path)
            self.assertEqual(
                result.log_path,
                Path(tmpdir) / "out" / "export_logs" / "skip-task.log",
            )

            rows = self.read_manifest(Path(tmpdir) / "out")
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["input"], str(task.input_path))
            self.assertEqual(row["output"], str(output_path))
            self.assertEqual(row["pos"], "left_wrist")
            self.assertEqual(row["mount_id"], "CARD_A")
            self.assertEqual(row["seq_id"], "006")
            self.assertEqual(row["status"], "skipped")
            self.assertIsNone(row["returncode"])
            self.assertEqual(row["log_path"], str(result.log_path))
            self.assertEqual(row["command"][0], "/fake/insta_media_exporter")
            self.assertIn("start", row)
            self.assertIn("end", row)

    def test_run_export_task_records_done_status_log_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter_path, _ = self.make_fake_exporter(tmpdir)
            task = self.make_task(tmpdir, task_id="done-task", exporter_path=str(exporter_path))

            result = run_export_task(task, overwrite=False)

            self.assertEqual(result.status, "done")
            self.assertEqual(result.returncode, 0)
            self.assertTrue(result.output_path.exists())
            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("fake stdout", log_text)
            self.assertIn("fake stderr", log_text)

            rows = self.read_manifest(Path(tmpdir) / "out")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "done")
            self.assertEqual(rows[0]["returncode"], 0)

    def test_run_export_task_records_failed_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter_path, _ = self.make_fake_exporter(tmpdir, exit_code=7)
            task = self.make_task(tmpdir, task_id="failed-task", exporter_path=str(exporter_path))

            result = run_export_task(task, overwrite=True)

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.returncode, 7)
            rows = self.read_manifest(Path(tmpdir) / "out")
            self.assertEqual(rows[0]["status"], "failed")
            self.assertEqual(rows[0]["returncode"], 7)

    def test_run_export_task_times_out_stalled_exporter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter_path, _ = self.make_fake_exporter(tmpdir, sleep_seconds=3.0)
            task = self.make_task(
                tmpdir,
                task_id="timeout-task",
                exporter_path=str(exporter_path),
                timeout_seconds=1,
            )

            result = run_export_task(task, overwrite=True)

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.returncode, 124)
            self.assertFalse(result.output_path.exists())
            log_text = result.log_path.read_text(encoding="utf-8")
            self.assertIn("TimeoutExpired", log_text)
            self.assertIn("--timeout-seconds 1", log_text)
            rows = self.read_manifest(Path(tmpdir) / "out")
            self.assertEqual(rows[0]["status"], "failed")
            self.assertEqual(rows[0]["returncode"], 124)

    def test_run_export_queue_limits_parallel_exporter_processes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter_path, max_seen_path = self.make_fake_exporter(
                tmpdir,
                sleep_seconds=0.2,
                track_parallel=True,
            )
            tasks = [
                self.make_task(
                    tmpdir,
                    task_id=f"parallel-{idx}",
                    input_path=str(Path(tmpdir) / f"VID_20260521_19123{idx}_00_{idx:03d}.insv"),
                    pos=f"pos_{idx}",
                    mount_id=f"CARD_{idx}",
                    seq_id=f"{idx:03d}",
                    exporter_path=str(exporter_path),
                )
                for idx in range(5)
            ]

            results = run_export_queue(tasks, max_parallel_exports=2, overwrite=True)

            self.assertEqual([result.status for result in results], ["done"] * 5)
            self.assertLessEqual(int(max_seen_path.read_text(encoding="utf-8")), 2)
            rows = self.read_manifest(Path(tmpdir) / "out")
            self.assertEqual(len(rows), 5)
            self.assertEqual({row["status"] for row in rows}, {"done"})
            self.assertFalse((Path(tmpdir) / "out" / "2026-05-21").exists())


if __name__ == "__main__":
    unittest.main()
