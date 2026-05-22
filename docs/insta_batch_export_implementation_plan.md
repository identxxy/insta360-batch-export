# Insta360 Batch Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit; this workspace is not a git repository and the user explicitly does not want automatic commits.

**Goal:** Build a local GUI and exporter tool that maps 5 Insta360 SD cards to body positions, manually selects videos from each position column, and exports 3840x1920 stabilized denoised panorama videos.

**Architecture:** Python/PySide6 owns scanning, sequence grouping, GUI state, task orchestration, logs, and manifests. A C++ `insta_media_exporter` executable owns one `.insv` to one `.mp4` MediaSDK export process, defaulting to CUDA/GPU. GUI runs multiple exporter processes up to `max_parallel_exports`.

**Tech Stack:** Python 3 standard library for core and tests, PySide6 for GUI, C++11 + Insta360 MediaSDK, `g++` build script using `/home/vox/instaSDK/env.sh`.

**Status on 2026-05-22:** Plan implementation is complete at the application layer. Python tests, Python compile checks, C++ exporter build, `ldd`, `/media/vox` scanning, fake-exporter queue verification, and real MediaSDK smoke investigation have been run. Real MediaSDK video export is blocked by the local NVIDIA kernel/user-space library mismatch documented in `docs/insta_batch_export_test_report.md`.

---

## File Structure

- Create `apps/insta_batch_export/README.md`: user-facing install, build, GUI launch, CLI launch, logs, known GPU/NVML caveat.
- Create `apps/insta_batch_export/requirements.txt`: GUI dependency list.
- Create `apps/insta_batch_export/gui_app.py`: PySide6 main window and worker thread integration.
- Create `apps/insta_batch_export/core/__init__.py`: package marker.
- Create `apps/insta_batch_export/core/media_scan.py`: SD card mount scanning and `VID_*.insv` filename parsing.
- Create `apps/insta_batch_export/core/sequence_grouping.py`: time-window grouping across assigned positions.
- Create `apps/insta_batch_export/core/export_jobs.py`: export task model, command building, process pool, logs, manifest.
- Create `apps/insta_batch_export/core/config_store.py`: JSON config load/save for body-position mapping and output options.
- Create `apps/insta_batch_export/cpp_exporter/insta_media_exporter.cc`: C++ MediaSDK CLI.
- Create `apps/insta_batch_export/cpp_exporter/build_exporter.sh`: `g++` build script sourced from repo `env.sh`.
- Create tests under `apps/insta_batch_export/tests/` using `unittest`, not pytest.

## Task 1: SDK smoke test and exporter CLI

**Files:**
- Create `apps/insta_batch_export/cpp_exporter/insta_media_exporter.cc`
- Create `apps/insta_batch_export/cpp_exporter/build_exporter.sh`
- Create `apps/insta_batch_export/README.md`

- [x] Inspect `media-sdk-root/usr/include/ins_stitcher.h` and vendor `example/main.cc` for exact MediaSDK calls.
- [x] Build a C++ CLI that accepts:
  - `--input <path>`
  - `--output <path>`
  - `--model-root <path>`
  - `--output-size 3840x1920`
  - `--stitch-type optflow|dynamicstitch|template|aistitch`
  - `--enable-flowstate`
  - `--enable-denoise`
  - `--disable-cuda`
  - `--image-processing-accel auto|cpu`
  - `--log-path <path>`
- [x] The default path must call `VideoStitcher::EnableCuda(true)`, `SetImageProcessingAccelType(ImageProcessingAccel::kAuto)`, `EnableFlowState(true)`, `EnableDenoise(true)`, and must not call `EnableDirectionLock(true)`.
- [x] The CLI must print progress lines and return non-zero on SDK error callback.
- [x] Build with `build_exporter.sh`, including `-lMediaSDK -lMNN_Cuda_Main`, `--disable-new-dtags`, local RPATH, and rpath-link.
- [x] Verify `ldd apps/insta_batch_export/cpp_exporter/build/insta_media_exporter` has no `not found`.
- [x] Run a minimal frame/image-sequence smoke test on the smallest valid `.insv` if MediaSDK supports it; otherwise record the exact failure in README and continue to app implementation.

## Task 2: scanning and sequence grouping core

**Files:**
- Create `apps/insta_batch_export/core/media_scan.py`
- Create `apps/insta_batch_export/core/sequence_grouping.py`
- Create `apps/insta_batch_export/tests/test_media_scan.py`
- Create `apps/insta_batch_export/tests/test_sequence_grouping.py`

- [x] Write failing `unittest` cases for parsing `VID_20260521_191237_00_006.insv`, rejecting non-VID names, and finding `LRV_20260521_191237_01_006.lrv`.
- [x] Implement `MediaItem`, `scan_mounts(root='/media/vox')`, `parse_media_filename(path)`, and `find_lrv_for_video(path)`.
- [x] Write failing `unittest` cases for grouping timestamp-adjacent files from different assigned positions even when seq ids differ.
- [x] Implement `group_sequences(items_by_pos, tolerance_seconds=3)` returning rows with `label`, `date`, `items_by_pos`, `complete`, and `missing_positions`.
- [x] Run `python3 -m unittest discover -s apps/insta_batch_export/tests -v` and verify tests pass.

## Task 3: export job orchestration

**Files:**
- Create `apps/insta_batch_export/core/export_jobs.py`
- Create `apps/insta_batch_export/tests/test_export_jobs.py`

- [x] Write failing tests for output path generation:
  `<output_dir>/<pos>/<YYYYMMDD_HHMMSS>_<mount_id>_<seq_id>.mp4`.
- [x] Write failing tests for skip behavior when output exists and `overwrite=False`.
- [x] Write failing tests for `max_parallel_exports` limiting concurrent subprocesses using a fake exporter command.
- [x] Implement `ExportTask`, `ExportResult`, `build_output_path`, `build_export_command`, `run_export_task`, and `run_export_queue`.
- [x] Ensure logs go to `<output_dir>/export_logs/<task_id>.log`.
- [x] Ensure JSONL manifest lines include input, output, pos, mount_id, seq_id, command, status, returncode, start/end timestamps, and log path.
- [x] Run unittest discovery and verify tests pass.

## Task 4: GUI and config

**Files:**
- Create `apps/insta_batch_export/core/config_store.py`
- Create `apps/insta_batch_export/gui_app.py`
- Create/update `apps/insta_batch_export/requirements.txt`
- Update `apps/insta_batch_export/README.md`

- [x] Implement config load/save at `~/.config/insta_batch_export_gui/config.json`.
- [x] GUI must show five fixed position selectors: `head`, `left_wrist`, `right_wrist`, `left_ankle`, `right_ankle`.
- [x] GUI must enforce one SD card per position and disable export until all five positions are assigned.
- [x] GUI must show sequence rows with date/time, completeness, and per-position basenames.
- [x] GUI must allow selecting output directory, overwrite checkbox, and `max_parallel_exports` spinbox defaulting to `1`.
- [x] GUI must run exports in a worker thread so the window remains responsive.
- [x] GUI must expose status updates: pending/running/done/failed/skipped.
- [x] If PySide6 is unavailable, `python3 apps/insta_batch_export/gui_app.py` must fail with a clear install message, not a raw traceback.

## Task 5: integration and verification

**Files:**
- Update `docs/insta_batch_export_gui_plan.md`
- Update `apps/insta_batch_export/README.md`

- [x] Run all Python unit tests.
- [x] Build C++ exporter and run `ldd`.
- [x] Run scanner against `/media/vox` and print detected mounts and grouped complete sequences.
- [x] Run a CLI dry/smoke export path against one `.insv`; if GPU fails because `nvidia-smi`/NVML is mismatched, record the exact error and CPU fallback command.
- [x] Run at least a fake-exporter queue test with `max_parallel_exports=2`.
- [x] Summarize residual risks: PySide6 not installed, NVML mismatch, real full-video export cost.
