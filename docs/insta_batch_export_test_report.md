# Insta360 Batch Export Test Report

Date: 2026-05-22

## Summary

The batch export application code is implemented and passes local unit/build checks. After reboot, the NVIDIA runtime is healthy and real MediaSDK smoke export succeeds through the Python export job path.

## Implemented Components

- C++ MediaSDK exporter CLI:
  - `apps/insta_batch_export/cpp_exporter/insta_media_exporter.cc`
  - `apps/insta_batch_export/cpp_exporter/build_exporter.sh`
- Python core:
  - `apps/insta_batch_export/core/media_scan.py`
  - `apps/insta_batch_export/core/sequence_grouping.py`
  - `apps/insta_batch_export/core/export_jobs.py`
  - `apps/insta_batch_export/core/config_store.py`
- GUI:
  - `apps/insta_batch_export/gui_app.py`
  - `apps/insta_batch_export/requirements.txt`
- User docs:
  - `apps/insta_batch_export/README.md`

## Passing Verification

### Python Tests

Command:

```bash
python3 -m unittest discover -s apps/insta_batch_export/tests -v
```

Result:

```text
Ran 23 tests in 1.704s
OK
```

Covered behavior:

- Parse `VID_*.insv` filenames.
- Find matching `LRV_*.lrv`.
- Scan `/media/vox`-style mount layout.
- Group sequence rows by timestamp even when seq ids differ.
- Build the manual per-position recent-video grid used by the GUI.
- Persist per-position `show_last_n` config with a default of `10`.
- Persist export profiles and per-position profile assignments.
- Generate output paths.
- Build exporter commands.
- Prepend the system `libcuda.so.1` to exporter `LD_PRELOAD` so MediaSDK does not use the sysroot `libcuda.so.1`.
- Skip existing outputs.
- Write logs and JSONL manifest.
- Enforce `max_parallel_exports=2` with a fake exporter.
- Fail stalled exporter subprocesses via `timeout_seconds` instead of waiting forever.

### Python Compile Check

Command:

```bash
python3 -m py_compile \
  apps/insta_batch_export/gui_app.py \
  apps/insta_batch_export/core/config_store.py \
  apps/insta_batch_export/core/media_scan.py \
  apps/insta_batch_export/core/sequence_grouping.py \
  apps/insta_batch_export/core/export_jobs.py
```

Result: exit 0.

### C++ Exporter Build

Command:

```bash
apps/insta_batch_export/cpp_exporter/build_exporter.sh
```

Result:

```text
Built exporter: /home/vox/instaSDK/apps/insta_batch_export/cpp_exporter/build/insta_media_exporter
```

### C++ Exporter Dynamic Link Check

Command:

```bash
ldd apps/insta_batch_export/cpp_exporter/build/insta_media_exporter
```

Result: exit 0, no `not found`.

Important libraries resolve to local SDK:

- `libMediaSDK.so`
- `libMNN_Cuda_Main.so`
- MediaSDK bundled `libssl.so.1.1`, `libcrypto.so.1.1`, `libnpp*.so.11`, `libtbb.so.2`, etc.

RPATH:

```text
$ORIGIN/../../../../media-sdk-root/usr/lib
```

CLI usage includes stalled-export protection:

```text
--timeout-seconds <seconds>    Cancel stalled export after this many seconds. Default: 21600.
```

### GUI Dependency And Launch

PySide6 is installed in the current base environment:

```text
PySide6 6.11.1
```

The GUI is currently launched as:

```text
python3 apps/insta_batch_export/gui_app.py
```

If PySide6 is absent in another environment, the app still exits with a clear install message instead of a raw traceback.

### Fake Exporter End-to-End Queue

A fake exporter was used to validate app-layer output layout and concurrency. Result statuses:

```text
['done', 'done', 'done', 'done', 'done']
```

The timeout regression also verifies that a stalled fake exporter exits through the app layer with:

```text
status=failed
returncode=124
```

Generated structure:

```text
export_logs/*.log
export_manifest.jsonl
head/20260521_191237_CARD0_000.mp4
left_wrist/20260521_191238_CARD1_001.mp4
right_wrist/20260521_191239_CARD2_002.mp4
left_ankle/20260521_191240_CARD3_003.mp4
right_ankle/20260521_191241_CARD4_004.mp4
```

## Real SD Card Scan

Command scanned `/media/vox`.

Detected mount counts:

```text
3234-3330: 5 videos
3334-3330: 5 videos
3832-3630: 5 videos
3934-3330: 7 videos
6234-3330: 2 videos
```

Using a temporary arbitrary position mapping, no synchronized five-camera row was found. This is why the GUI now uses manual per-cell video selection instead of requiring complete `5/5` sequence rows.

## Real MediaSDK Export Result

After reboot, `nvidia-smi` is healthy:

```text
Driver Version: 595.71.05
CUDA Version: 13.2
```

Direct CLI without environment override still failed because the exporter RPATH must include `media-sdk-root/usr/lib`, and that sysroot contains its own `libcuda.so.1`. With `LD_PRELOAD=/lib/x86_64-linux-gnu/libcuda.so.1`, the same real `.insv` succeeds:

```text
done output=/home/vox/instaSDK/tmp/smoke_after_reboot/smoke_1920x960_preload.mp4 elapsed_seconds=5.93745
```

The Python export job path now injects the same preload automatically. Verification through `run_export_task()`:

```text
done 0 /home/vox/instaSDK/tmp/smoke_flat_layout/head/20260519_195944_3334-3330_001.mp4
```

The same run wrote logs and manifest without any date directory:

```text
/home/vox/instaSDK/tmp/smoke_flat_layout/export_logs/20260519_195944_3334-3330_001_head.log
/home/vox/instaSDK/tmp/smoke_flat_layout/export_manifest.jsonl
```

## Root Cause Update

Before reboot, the workstation NVIDIA kernel module and user-space libraries did not match:

```text
kernel module: 595.58.03
NVML/user-space library: 595.71
```

Before reboot, `nvidia-smi` reported:

```text
Driver/library version mismatch
```

After reboot, system NVIDIA runtime is fixed. The remaining export-specific issue was the SDK sysroot `libcuda.so.1` being selected before the system driver library. GUI/Python export jobs now address that by prepending the system driver library to `LD_PRELOAD`.

## Next Full Verification

The reduced 1920x960 smoke has passed. Next, test normal 4K through the Python job path or GUI:

```bash
python3 apps/insta_batch_export/gui_app.py
```

Direct CLI still needs the system CUDA-driver preload:

```bash
LD_PRELOAD=/lib/x86_64-linux-gnu/libcuda.so.1 \
apps/insta_batch_export/cpp_exporter/build/insta_media_exporter \
  --input <input.insv> \
  --output <output.mp4> \
  --model-root /home/vox/instaSDK/libMediaSDK-dev-3.1.1.0-20250922_191110-amd64/models \
  --output-size 3840x1920 \
  --timeout-seconds 21600
```
