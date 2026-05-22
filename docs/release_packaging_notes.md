# Linux Release Packaging Notes

Date: 2026-05-22

## Short Answer

A Linux release build is technically feasible, but a public release that bundles
Insta360 MediaSDK runtime libraries, model files, or SDK binaries should not be
published unless Insta360 explicitly grants redistribution permission.

The current local SDK package does not include a visible license file that grants
redistribution rights. The official SDK guide says developers obtain the SDK by
application approval, and the official GitHub MediaSDK page also points users to
the SDK application flow.

## Safe Release Modes

### Source-only public release

Publish this repository with GUI/source/build scripts only. Users install or
point to their own Insta360 SDK:

- `INSTA_MEDIASDK_LIB=/path/to/media-sdk-root/usr/lib/libMediaSDK.so`
- `MEDIA_SDK_LIB_DIR=/path/to/media-sdk-root/usr/lib`
- `MEDIA_SDK_ROOT=/path/to/media-sdk-root/usr`
- `INSTA_MEDIA_MODELS_DIR=/path/to/libMediaSDK-dev-*/models`

`INSTA_MEDIASDK_LIB`, `MEDIA_SDK_LIB_DIR`, and `MEDIA_SDK_ROOT` are alternatives
for resolving the MediaSDK runtime library directory. `INSTA_MEDIA_MODELS_DIR`
is still required for the model files.

This is the safest public distribution model.

### Binary app without bundled Insta360 SDK

Package the Python GUI and our C++ wrapper as AppImage or a portable tarball, but
do not include proprietary SDK libraries or model files. At first launch, the app
asks users to locate their SDK directory.

This reduces setup friction while keeping SDK acquisition separate.

### Private/internal binary bundle

For lab/internal use, a tarball can bundle:

- PySide6 runtime
- `insta_media_exporter`
- `libMediaSDK.so` and its runtime dependencies
- MediaSDK model directory

This should be treated as private redistribution within the licensed group unless
Insta360 grants broader redistribution rights.

Build it locally with:

```bash
apps/insta_batch_export/packaging/build_offline_bundle.sh
```

The generated bundle is written under `dist/` and includes a `run_gui.sh`
launcher. The launcher sets SDK runtime paths to the bundle-local copies.

## Not Safe By Default

Do not publish a public GitHub release or public download that includes:

- `libMediaSDK.so`
- `MediaSDKTest`
- MediaSDK model files
- the original SDK zip/deb/tar packages
- bundled CameraSDK/MediaSDK headers and examples

The technical packaging is straightforward, but the license boundary is not.

## Public One-click Bundle Decision

Do not create or push a public one-click Linux bundle that includes proprietary
Insta360 SDK binaries or model files without written redistribution permission.

Adding README attribution such as "built with Insta360 SDK 3.1.1" is useful for
transparency, but it does not grant redistribution rights. The absence of a
visible prohibition in the local SDK package is not the same as permission to
redistribute copyrighted binary libraries, model files, or SDK packages.

Acceptable one-click variants:

- Public AppImage/tarball that bundles only our GUI, our exporter wrapper, and
  open/runtime dependencies, then asks the user to select an SDK directory.
- Private/internal tarball for an authorized lab machine or licensed group.
- Public SDK-bundled release only after written permission from Insta360.

## Recommended Path

1. Keep the public repo source-only.
2. Add a release artifact that contains our code, GUI, and wrapper only.
3. Require users to provide `INSTA_MEDIASDK_LIB` or `MEDIA_SDK_ROOT`, plus
   `INSTA_MEDIA_MODELS_DIR`.
4. If a truly one-click public binary is needed, request written redistribution
   permission from Insta360 before bundling SDK binaries/models.

## References

- Official SDK guide: developers apply for SDK access and receive a download
  link after approval.
- Official Desktop MediaSDK-Cpp GitHub page: the "How to get?" section directs
  developers to apply for the latest SDK.
