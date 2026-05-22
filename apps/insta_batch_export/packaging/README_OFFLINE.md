# Insta360 Batch Export Offline Bundle

This directory is a private/internal portable Linux x86_64 bundle. It includes
the batch export GUI, the C++ MediaSDK exporter wrapper, and local Insta360
MediaSDK runtime files copied from the build machine.

Do not upload this bundle to a public repository or public release channel unless
you have explicit redistribution permission for the bundled Insta360 SDK files.

## Requirements On The Target Machine

- Linux x86_64 desktop.
- NVIDIA driver installed and visible through `nvidia-smi` for GPU export.
- Five Insta360 SD cards mounted under `/media/vox`.
- `ffprobe` is optional; without it, the GUI may not show source recording
  resolution/fps labels.

The bundle intentionally does not include `libcuda.so.1`. CUDA driver libraries
must come from the target machine's NVIDIA driver installation.

## Run

From the bundle root:

```bash
./run_gui.sh
```

The launcher sets:

```bash
INSTA_EXPORTER_PATH=<bundle>/bin/insta_media_exporter
INSTA_MEDIASDK_LIB=<bundle>/sdk/lib/libMediaSDK.so
MEDIA_SDK_LIB_DIR=<bundle>/sdk/lib
INSTA_MEDIA_MODELS_DIR=<bundle>/sdk/models
LD_LIBRARY_PATH=<bundle>/sdk/lib:$LD_LIBRARY_PATH
```

## Output Layout

Exported videos:

```text
<output_dir>/<pos>/<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4
```

Logs:

```text
<output_dir>/export_logs/<task_id>.log
<output_dir>/export_manifest.jsonl
```

