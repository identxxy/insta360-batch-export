# Online User Setup

This public repository does not include Insta360 SDK binaries, model files, or
sample footage. Online users must obtain Insta360 MediaSDK themselves before
exporting `.insv` videos.

## 1. Get Insta360 MediaSDK

Apply for the SDK through Insta360's official developer channel:

- SDK guide: https://onlinemanual.insta360.com/developer/en-us/resource/sdk
- Desktop MediaSDK-Cpp page: https://github.com/Insta360Develop/Desktop-MediaSDK-Cpp

After approval, download the Linux x86_64 MediaSDK package.

## 2. Put SDK Files On Disk

The app needs two SDK paths:

1. The MediaSDK runtime library directory containing `libMediaSDK.so` and its
   companion runtime libraries.
2. The MediaSDK `models/` directory.

A recommended layout is:

```text
~/insta360-sdk/
  media-sdk-root/
    usr/
      include/
      lib/
        libMediaSDK.so
        libMNN.so
        libMNN_Cuda_Main.so
        libnpp*.so.11
        ...
  libMediaSDK-dev-3.1.1.0-*/ 
    models/
      *.ins
      coolingshell/
```

Do not copy only `libMediaSDK.so`; keep the other `.so` files from the same SDK
`lib/` directory next to it. The exporter resolves them through
`LD_LIBRARY_PATH`.

The app does not need the SDK's bundled `libcuda.so.1`. GPU export should use
the target machine's installed NVIDIA driver.

## 3. Set Runtime Environment

Before running the GUI:

```bash
export INSTA_MEDIASDK_LIB=~/insta360-sdk/media-sdk-root/usr/lib/libMediaSDK.so
export INSTA_MEDIA_MODELS_DIR=~/insta360-sdk/libMediaSDK-dev-3.1.1.0-*/models
```

Alternative library path variables are also supported:

```bash
export MEDIA_SDK_LIB_DIR=~/insta360-sdk/media-sdk-root/usr/lib
# or
export MEDIA_SDK_ROOT=~/insta360-sdk/media-sdk-root/usr
```

The GUI/export queue automatically prepends the resolved SDK library directory
to `LD_LIBRARY_PATH` for the exporter subprocess.

## 4. Install App Dependencies

```bash
python3 -m pip install -r apps/insta_batch_export/requirements.txt
```

`ffprobe` from FFmpeg is optional but recommended so the GUI can label source
recording resolution and frame rate in each video cell.

## 5. Build The Exporter

If you run from source, build the C++ wrapper:

```bash
export MEDIA_SDK_ROOT=~/insta360-sdk/media-sdk-root/usr
apps/insta_batch_export/cpp_exporter/build_exporter.sh
```

## 6. Run

```bash
python3 apps/insta_batch_export/gui_app.py
```

The GUI expects SD cards under:

```text
/media/vox/<card>/DCIM/Camera01/VID_*.insv
```

