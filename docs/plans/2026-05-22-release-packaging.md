# Release Packaging Plan

Date: 2026-05-22

## Goal

Support two release modes for the Insta360 batch export app:

1. Public online users run the app after obtaining Insta360 MediaSDK themselves.
2. A private offline USB bundle includes the SDK runtime and models for internal
   one-click use.

## Non-goals

- Do not publish Insta360 SDK binaries, model files, sample footage, or SDK
  archives to the public GitHub repository.
- Do not rely on the SDK's bundled `libcuda.so.1`; target machines must use
  their installed NVIDIA driver.

## Current Behavior

- Public repo contains source, tests, and docs only.
- Export subprocesses can resolve MediaSDK runtime libraries from:
  - `INSTA_MEDIASDK_LIB`
  - `MEDIA_SDK_LIB_DIR`
  - `MEDIA_SDK_ROOT`
- Export subprocesses use `INSTA_MEDIA_MODELS_DIR` for MediaSDK models.

## Implementation Steps

1. Document public online setup clearly in root README and app README.
2. Add `INSTA_EXPORTER_PATH` support so a packaged GUI can use a bundle-local
   exporter binary.
3. Add private offline packaging files:
   - `apps/insta_batch_export/packaging/build_offline_bundle.sh`
   - `apps/insta_batch_export/packaging/README_OFFLINE.md`
4. Build a local `dist/insta360-batch-export-offline-linux-x86_64/` bundle.
5. Verify:
   - Python unit tests.
   - Python compile checks.
   - Bundle layout includes GUI app, exporter, SDK libs excluding `libcuda.so.1`,
     and models.
   - Bundle launcher reports help/startup behavior without missing library
     errors.

## Risks

- The offline bundle is private/internal because it contains proprietary SDK
  binaries and models.
- PyInstaller bundles are tied to Linux/glibc compatibility of the build host.
- Target machines still need a compatible NVIDIA driver for GPU export.
