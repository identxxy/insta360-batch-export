# Insta360 Batch Export GUI

Local GUI for mapping five Insta360 SD cards to body positions and batch-exporting manually selected Insta360 videos.

## Layout

- `gui_app.py`: PySide6 GUI.
- `core/media_scan.py`: scans `/media/vox/*/DCIM/Camera01/VID_*.insv`.
- `core/sequence_grouping.py`: legacy timestamp grouping helper kept for tests/reference.
- `core/export_jobs.py`: runs exporter subprocesses, logs, manifest, skip/overwrite, concurrency.
- `cpp_exporter/insta_media_exporter.cc`: one `.insv` to one panorama `.mp4` MediaSDK CLI.
- `cpp_exporter/build_exporter.sh`: builds the C++ exporter against the local SDK.

## Build Exporter

```bash
cd /home/vox/instaSDK
apps/insta_batch_export/cpp_exporter/build_exporter.sh
ldd apps/insta_batch_export/cpp_exporter/build/insta_media_exporter
```

The exporter defaults to:

- output size: `3840x1920`
- stitch type: `optflow`
- FlowState: enabled
- denoise: enabled
- direction lock: disabled
- CUDA: enabled
- image processing accel: `auto`
- stalled-export timeout: `21600` seconds

The Python GUI/export queue automatically prepends the system CUDA driver library
(`/lib/x86_64-linux-gnu/libcuda.so.1` when present) to `LD_PRELOAD`. This is
needed because the MediaSDK sysroot also contains a `libcuda.so.1`, and the
exporter RPATH must still point at that sysroot for MediaSDK's bundled
dependencies.

Direct CLI smoke test with the same CUDA-driver preload:

```bash
LD_PRELOAD=/lib/x86_64-linux-gnu/libcuda.so.1 \
apps/insta_batch_export/cpp_exporter/build/insta_media_exporter \
  --input <input.insv> \
  --output <output.mp4> \
  --model-root /home/vox/instaSDK/libMediaSDK-dev-3.1.1.0-20250922_191110-amd64/models \
  --output-size 1920x960 \
  --timeout-seconds 120
```

CPU fallback for debugging:

```bash
apps/insta_batch_export/cpp_exporter/build/insta_media_exporter \
  --input <input.insv> \
  --output <output.mp4> \
  --model-root /home/vox/instaSDK/libMediaSDK-dev-3.1.1.0-20250922_191110-amd64/models \
  --disable-cuda \
  --image-processing-accel cpu \
  --timeout-seconds 600
```

## GUI Setup

PySide6 is required for the GUI:

```bash
cd /home/vox/instaSDK
python3 -m pip install -r apps/insta_batch_export/requirements.txt
python3 apps/insta_batch_export/gui_app.py
```

If you prefer conda:

```bash
conda create -n insta-export python=3.13 -y
conda activate insta-export
python -m pip install -r apps/insta_batch_export/requirements.txt
python apps/insta_batch_export/gui_app.py
```

## Workflow

1. Insert/mount the five SD cards under `/media/vox`.
2. Start the GUI.
3. Bind each position to exactly one SD card:
   - `head`
   - `left_wrist`
   - `right_wrist`
   - `left_ankle`
   - `right_ankle`
4. For each position, adjust `Show last N videos` if needed. Default is `10`.
5. Choose or create export profiles. A profile controls resolution, FlowState,
   denoise, and direction lock.
6. Assign a profile to each position. All positions use `Default 4K` unless
   changed.
7. Click video cells to toggle selected/unselected.
8. Choose an output directory.
9. Set `max_parallel_exports`. Default is `1`; try `2` first on a large single GPU.
10. Start export.

Default profile:

```text
Default 4K:
  resolution: 3840x1920
  FlowState: on
  denoise: on
  direction lock: off
```

Output path:

```text
<output_dir>/<pos>/<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4
```

Example:

```text
/data/export/head/20260521_191237_3934-3330_006.mp4
```

## Logs And Manifest

```text
<output_dir>/export_manifest.jsonl
<output_dir>/export_logs/<task_id>.log
```

Manifest rows include input, output, position, mount id, seq id, command, status, return code, timeout seconds, start/end timestamps, and log path.

## Current GPU Status

After reboot, `nvidia-smi` reports a working RTX 4090 runtime:

```text
Driver Version: 595.71.05
CUDA Version: 13.2
```

Real MediaSDK smoke export has succeeded through the Python export job path at
`1920x960`. The GUI uses the same path.

## Verification

```bash
cd /home/vox/instaSDK
python3 -m unittest discover -s apps/insta_batch_export/tests -v
python3 -m py_compile \
  apps/insta_batch_export/gui_app.py \
  apps/insta_batch_export/core/config_store.py \
  apps/insta_batch_export/core/media_scan.py \
  apps/insta_batch_export/core/sequence_grouping.py \
  apps/insta_batch_export/core/export_jobs.py
apps/insta_batch_export/cpp_exporter/build_exporter.sh
ldd apps/insta_batch_export/cpp_exporter/build/insta_media_exporter
```
