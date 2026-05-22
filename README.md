# Insta360 Batch Export GUI

A local GUI for batch-exporting Insta360 `.insv` videos from five body-mounted
panorama cameras.

The intended capture setup uses five cameras assigned to:

- `head`
- `left_wrist`
- `right_wrist`
- `left_ankle`
- `right_ankle`

The GUI maps SD cards mounted under `/media/vox` to these positions, lets the
user manually select recent videos from each camera, and exports stabilized,
denoised equirectangular panorama videos through Insta360 MediaSDK.

## Why Manual Selection

In practice, the cameras' clocks may drift or be set to different dates. This
tool therefore does not require automatic complete `5/5` timestamp grouping.
Each position column shows the last N videos for that camera, and each video
cell can be toggled selected/unselected independently.

## Output Layout

Exported videos are written directly under each body position:

```text
<output_dir>/<pos>/<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4
```

Logs and manifest are stored at the output root:

```text
<output_dir>/export_logs/<task_id>.log
<output_dir>/export_manifest.jsonl
```

Example:

```text
/data/insta_exports/head/20260521_191237_3934-3330_006.mp4
/data/insta_exports/export_logs/20260521_191237_3934-3330_006_head.log
/data/insta_exports/export_manifest.jsonl
```

## Export Settings

The exporter defaults to:

- output size: `3840x1920`
- stitch type: `optflow`
- FlowState stabilization: enabled
- denoise: enabled
- direction lock: disabled
- CUDA: enabled
- image processing acceleration: `auto`

## Repository Scope

This repository contains only the GUI, exporter wrapper source, tests, and
documentation. It does not include Insta360 CameraSDK, MediaSDK, SDK models, or
sample footage. Install those separately according to Insta360's license terms.

## Requirements

- Linux desktop with Python 3
- PySide6 for the GUI
- `ffprobe` from FFmpeg for source recording resolution/fps labels
- `g++` for the C++ exporter
- Insta360 MediaSDK installed locally
- NVIDIA driver/CUDA runtime if using GPU export

Set these environment variables before building/running exports:

```bash
export MEDIA_SDK_ROOT=/path/to/media-sdk-root/usr
export INSTA_MEDIA_MODELS_DIR=/path/to/libMediaSDK-dev-*/models
```

`MEDIA_SDK_ROOT` must contain `include/` and `lib/`. For binary releases that
do not build against the SDK, users can instead point directly at the runtime
library:

```bash
export INSTA_MEDIASDK_LIB=/path/to/media-sdk-root/usr/lib/libMediaSDK.so
export INSTA_MEDIA_MODELS_DIR=/path/to/libMediaSDK-dev-*/models
```

The export queue resolves `INSTA_MEDIASDK_LIB`, `MEDIA_SDK_LIB_DIR`, or
`MEDIA_SDK_ROOT`, then prepends the resolved directory to `LD_LIBRARY_PATH` for
the exporter subprocess.

For the full online-user setup, including where to place SDK files after
approval, see:

```text
docs/online_user_setup.md
```

## Install GUI Dependencies

```bash
python3 -m pip install -r apps/insta_batch_export/requirements.txt
```

## Build Exporter

```bash
apps/insta_batch_export/cpp_exporter/build_exporter.sh
ldd apps/insta_batch_export/cpp_exporter/build/insta_media_exporter
```

The build script also supports the original local development layout where a
repo-local `env.sh` exports `MEDIA_SDK_ROOT`.

## Run GUI

```bash
python3 apps/insta_batch_export/gui_app.py
```

Workflow:

1. Mount five SD cards under `/media/vox`.
2. Bind each body position to exactly one SD card.
3. Adjust `Show last N videos` per position if needed.
4. Choose or create export profiles. A profile controls resolution,
   FlowState, denoise, and direction lock.
5. Assign a profile to each position. All positions use `Default 4K` unless
   changed.
6. Check each video cell's source recording label. The GUI probes visible
   `.insv` files with `ffprobe` and shows source stream resolution and frame
   rate, for example `source 2x 1920x1920 @ 29.97fps`.
7. Click video cells to select/unselect them.
8. Choose an output directory.
9. Set `max_parallel_exports`.
10. Start export.

The default profile is:

```text
Default 4K:
  resolution: 3840x1920
  FlowState: on
  denoise: on
  direction lock: off
```

Resolution presets:

- `3840x1920`: default 4K panorama.
- `7680x3840`: 8K panorama when the source footage and hardware support it.
- `1920x960`: smoke/debug export.
- `960x480`: fast preview export.

## CUDA Driver Library Note

Some MediaSDK distributions include a `libcuda.so.1` inside the SDK sysroot.
The Python export queue automatically prepends the system CUDA driver library
(`/lib/x86_64-linux-gnu/libcuda.so.1` when present) to `LD_PRELOAD` so the SDK
uses the installed NVIDIA driver instead of the bundled stub/compat library.

If running the C++ CLI directly and you see
`CUDA_ERROR_SYSTEM_DRIVER_MISMATCH`, run it like this:

```bash
LD_PRELOAD=/lib/x86_64-linux-gnu/libcuda.so.1 \
apps/insta_batch_export/cpp_exporter/build/insta_media_exporter \
  --input <input.insv> \
  --output <output.mp4> \
  --model-root "$INSTA_MEDIA_MODELS_DIR" \
  --output-size 3840x1920 \
  --timeout-seconds 21600
```

## Tests

```bash
python3 -m unittest discover -s apps/insta_batch_export/tests -v
python3 -m py_compile \
  apps/insta_batch_export/gui_app.py \
  apps/insta_batch_export/core/config_store.py \
  apps/insta_batch_export/core/media_scan.py \
  apps/insta_batch_export/core/sequence_grouping.py \
  apps/insta_batch_export/core/export_jobs.py
```

## Development Notes

- GUI config is stored at
  `~/.config/insta_batch_export_gui/config.json`.
- Each `.insv` is treated as one complete source video.
- Export tasks are separate subprocesses, so a failed SDK export does not crash
  the GUI process.
- `max_parallel_exports=1` is the safest default. Increase cautiously after
  checking GPU memory, NVENC load, CPU usage, and SD-card I/O.
- Private offline bundles can be built with
  `apps/insta_batch_export/packaging/build_offline_bundle.sh`, but generated
  `dist/` bundles contain SDK binaries/models and must not be published.
