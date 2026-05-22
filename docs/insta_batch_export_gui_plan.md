# Insta360 五相机批量导出 GUI 开发计划

状态：方案 A 已实施到 app-layer，并已完成 Python 单测、C++ exporter 编译、fake-exporter 端到端验证和真实 MediaSDK 1920x960 smoke export。GUI 已从“自动 complete 5/5 sequence 选择”改为“每个 pos 最近 N 个视频的手动 cell 选择”，以适配 5 个相机时钟不同步的采集。输出目录已改为 `<output_dir>/<pos>/`，日志和 manifest 位于 `<output_dir>/export_logs/` 与 `<output_dir>/export_manifest.jsonl`。

## 目标

开发一个本地 GUI 工具，用于从 `/media/vox` 下的 5 张 Insta360 SD 卡中选择相机位置、手动选择要导出的视频，并统一调用 MediaSDK 批量导出 4K 全景视频到：

```text
<output_dir>/<pos>/
```

其中 `pos` 固定为：

- `head`
- `left_wrist`
- `right_wrist`
- `left_ankle`
- `right_ankle`

导出配置固定为：

- 输出全景分辨率：`3840x1920`，即 2:1 equirectangular 4K panorama。
- 开防抖：SDK `-enable_flowstate`。
- 开降噪：SDK `-enable_denoise`。
- 不开方向锁定：不传 `-enable_directionlock`。

## 当前环境事实

本地 SDK 已在 `/home/vox/instaSDK` 配好：

- CameraSDK: `/home/vox/instaSDK/CameraSDK-20251104_115504-2.1.1.1-Linux`
- MediaSDK local sysroot: `/home/vox/instaSDK/media-sdk-root/usr`
- MediaSDK models: `/home/vox/instaSDK/libMediaSDK-dev-3.1.1.0-20250922_191110-amd64/models`
- 已验证示例二进制：
  - `/home/vox/instaSDK/build/camera_sdk_demo`
  - `/home/vox/instaSDK/build/media_sdk_demo`

`/media/vox` 当前可见 5 个 SD 卡挂载点：

- `/media/vox/3234-3330`
- `/media/vox/3832-3630`
- `/media/vox/3934-3330`
- `/media/vox/6234-3330`
- `/media/vox/3334-3330`

主要视频文件位于 `DCIM/Camera01/VID_*.insv`，对应低清预览为 `LRV_*.lrv`。文件名中包含采集时间和 seq index，例如：

```text
VID_20260521_191237_00_006.insv
```

## 整体框架

采用方案 A：“Python GUI + C++ MediaSDK exporter CLI”的双层结构。

GUI 层用 Python + PySide6 实现，负责扫描 SD 卡、解析文件列表、相机位置绑定、序列选择、任务队列、日志展示、失败重试和用户交互。SDK 执行层用一个小型 C++ CLI 封装 MediaSDK，负责单个 `.insv` 到 panorama mp4 的确定性导出。

核心原因：MediaSDK 是 C++ 二进制 SDK，导出任务本质是重 CPU/GPU/IO 的长进程。把导出封装成独立 CLI 进程，可以隔离 SDK 崩溃、释放 GPU/CPU 内存更可靠，并且 GUI 主线程不会被 SDK 阻塞。Python GUI 只做 orchestration，不直接链接复杂 SDK，调试边界更清楚。

优点：

- GUI 开发快，文件扫描、表格、任务状态、日志、配置保存更方便。
- C++ exporter 直接链接 MediaSDK，保持 SDK ABI 边界清晰。
- 每个导出任务是独立进程，失败不会拖死整个 GUI。
- 后续可以无 GUI 地调用 CLI 做批处理。

缺点：

- 需要维护 Python 和 C++ 两个构建入口。
- 需要定义清楚 GUI 到 exporter 的命令行协议。

## GPU / CUDA 使用策略

MediaSDK 可以使用 GPU。依据来自本地 SDK：

- `media-sdk-root/usr/include/ins_stitcher.h` 中 `VideoStitcher::EnableCuda(bool enable)` 的注释说明：如果有 CUDA 加速环境，可以设为 true，用于提高 stitching 速度。
- 同一头文件说明单个进程实例不支持多 GPU；如果要利用多 GPU，需要创建多个进程实例分别对应各 GPU。
- vendor 示例 `libMediaSDK-dev-3.1.1.0-20250922_191110-amd64/example/main.cc` 默认 `enable_cuda = true`，只有传 `-disable_cuda` 时才关闭 CUDA，并且视频导出路径会调用 `video_stitcher->EnableCuda(enable_cuda)`。
- MediaSDK README 标注 CUDA 版本为 11.7；本地 `media-sdk-root/usr/lib` 也包含 `libMNN_Cuda_Main.so`、`libnpp*.so.11`、`libcuda.so.1`、`libcudart.so.8.0.61` 等 CUDA/NPP 相关库。

因此 exporter 默认启用 GPU：调用 `VideoStitcher::EnableCuda(true)`，不传 `-disable_cuda` 等价选项，并保持 `ImageProcessingAccel::kAuto`。为调试保留 CLI 参数 `--disable-cuda` 和 `--image-processing-accel cpu`，但 GUI 第一版不暴露它们，避免误关 GPU。

单 GPU 可以并发跑多个导出任务，前提是显存、CUDA context、解码/编码引擎、CPU 和 SD 卡 IO 都够。MediaSDK 的限制是“单个进程实例不支持多 GPU”，这不等于“一张 GPU 只能跑一个进程”；多个 exporter 进程可以共享同一张 GPU，只是吞吐是否提升需要实测。

第一版 GUI 支持可配置并发：

- 默认 `max_parallel_exports = 1`，保证稳定。
- GUI 提供高级设置，允许用户调到 `2`、`3` 或 `4`。
- 调度层用独立 exporter 进程池，而不是在同一进程里开多个 SDK 对象。
- 单 GPU 机器统一设置 `CUDA_VISIBLE_DEVICES=0` 给 exporter 进程。
- 推荐实施验收时 benchmark `1/2/3` 并发，记录 wall time、失败率、GPU 显存和 SD 卡 IO 情况，再决定日常默认值。

当前本机可从 `/proc/driver/nvidia/gpus` 看到一张 `NVIDIA GeForce RTX 4090`，但 `nvidia-smi` 当前报 `Driver/library version mismatch`：kernel module 为 `595.58.03`，NVML library 为 `595.71`。这不改变设计，但实施前需要把 GPU runtime smoke test 加进验收；如果 CUDA 初始化失败，先修驱动/NVML 一致性或重启，再做 GPU 导出测试。

## 功能设计

### 1. SD 卡扫描

启动时扫描 `/media/vox/*/DCIM/Camera01/VID_*.insv`，同时读取同目录下的 `.lrv` 是否存在。扫描结果按 SD 卡挂载点聚合，并解析：

- `mount_id`: 例如 `3234-3330`
- `mount_path`: 例如 `/media/vox/3234-3330`
- `video_path`
- `timestamp`: 从文件名解析，如 `2026-05-21 19:12:37`
- `seq_id`: 从文件名末尾解析，如 `006`
- `basename`: 原始文件名
- `has_lrv`

理论上，五机同步采集的同一次 capture 会在各卡上形成时间接近的一组 `.insv`。但当前样例显示不同卡之间 seq index 不一定一致，例如同一时间 `20260521_191237` 在不同卡上可能是 `006` 和 `003`，因此 GUI 不应只按 seq index 对齐，而应以时间窗口为主、seq index 为辅助。

### 2. 相机位置绑定

GUI 提供 5 个位置槽位：

- head
- left_wrist
- right_wrist
- left_ankle
- right_ankle

每个槽位用下拉框选择一个 SD 卡挂载点。约束：

- 一个 SD 卡只能绑定到一个 pos。
- 5 个 pos 必须全部绑定后才允许进入导出。
- 可保存上次绑定到本地 config，例如 `~/.config/insta_batch_export_gui/config.json`。

### 3. sequence 选择

GUI 显示一个按采集时间聚合的 sequence table。推荐聚合策略：

1. 收集所有已绑定 SD 卡上的 `VID_*.insv`。
2. 按 timestamp 排序。
3. 使用时间窗口聚类，默认同一次 capture 的跨卡时间差阈值为 `±3s`。
4. 对每个聚类生成一行候选 sequence，显示：
   - sequence label: 例如 `2026-05-21 19:12:37`
   - 每个 pos 是否有匹配文件
   - 每个 pos 的具体 basename
   - 完整性状态：5/5、4/5 等

当前 GUI 不再要求 timestamp 聚类得到完整 5/5 sequence。用户在每个 pos 列中查看最近 N 个视频，并逐个点击 cell 切换 selected/unselected。

### 4. 输出目录规则

用户选择 `output_dir` 后，GUI 只按 pos 组织输出，不再按源文件日期建目录，因为不同相机时钟可能不一致：

```text
<output_dir>/<pos>/<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4
```

建议文件名使用稳定且可追踪的格式：

```text
<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4
```

例子：

```text
/data/export/head/20260521_191237_3934-3330_006.mp4
```

文件名保留源 timestamp、源卡和源 seq index，便于之后追溯。

已确认：输出文件名采用 `<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4`。

### 5. 导出执行

GUI 生成导出任务队列。每个任务对应一个 input `.insv` 和一个 output `.mp4`。任务调用 C++ exporter CLI：

```bash
insta_media_exporter \
  --input <video.insv> \
  --output <output.mp4> \
  --model-root <models_dir> \
  --output-size 3840x1920 \
  --stitch-type optflow \
  --enable-flowstate \
  --enable-denoise
```

不提供 `--enable-directionlock`，因此方向锁定关闭。

已确认：每个 `.insv` 文件就是一个相机的完整全景视频输入，不需要额外配对同一相机的多个视频文件。

并发策略默认 `1`，但 GUI 提供高级设置 `max_parallel_exports`，允许同一张 GPU 上同时跑多个独立 exporter 进程。建议实际使用时从 `2` 开始试；如果显存、编码器或 SD 卡 IO 成为瓶颈，就降回 `1`。任务队列必须保证同一时刻 running 任务数不超过该设置。

### 6. 状态和错误处理

任务状态：

- pending
- running
- done
- failed
- skipped

失败处理：

- exporter 非零退出码标记为 failed。
- stderr/stdout 写入 `<output_dir>/export_logs/<task_id>.log`。
- 若输出文件已存在，默认 skip；GUI 提供 overwrite checkbox。
- 每个 sequence 完成后写 manifest，记录输入、输出、参数、耗时、退出码。

manifest 建议为 JSONL：

```text
<output_dir>/export_manifest.jsonl
```

每行一个导出任务，便于后续脚本读。

## 文件结构计划

建议创建：

```text
apps/insta_batch_export/
  README.md
  requirements.txt
  gui_app.py
  core/
    media_scan.py
    sequence_grouping.py
    export_jobs.py
    config_store.py
  cpp_exporter/
    CMakeLists.txt
    insta_media_exporter.cc
  tests/
    test_media_scan.py
    test_sequence_grouping.py
    fixtures/
```

如果系统没有 `cmake`，第一版同时提供 `build_exporter.sh`，直接用 `g++` 链接 MediaSDK，沿用当前 `build_examples.sh` 的链接参数。

## subagent 开发拆分

实施时建议使用 4 个 subagent，加一个主 session 负责集成和最终判断。

### Subagent 1：C++ exporter CLI

职责：

- 封装 MediaSDK 单文件导出。
- 暴露稳定 CLI 参数。
- 固定输出配置：4K、flowstate、denoise、no directionlock。
- 默认启用 GPU：`VideoStitcher::EnableCuda(true)`，`ImageProcessingAccel::kAuto`。
- 复用当前本地 SDK 链接方式，处理 `libMNN_Cuda_Main.so` direct dependency。

交付文件：

- `apps/insta_batch_export/cpp_exporter/insta_media_exporter.cc`
- `apps/insta_batch_export/cpp_exporter/build_exporter.sh`
- 可选 `CMakeLists.txt`

验收标准：

- 在无输入素材时打印清晰 usage 并返回非零。
- 对一个存在的 `.insv` 能生成目标 `.mp4`，或在 SDK 不支持该素材时给出可读错误日志。
- `ldd` 检查 exporter 没有 `not found`。
- 命令行参数能覆盖 input/output/model-root，但导出策略默认固定为目标配置。
- 默认导出路径调用 `EnableCuda(true)`；传 `--disable-cuda` 时调用 `EnableCuda(false)`，用于 CPU fallback 调试。

### Subagent 2：扫描和 sequence grouping core

职责：

- 扫描 `/media/vox` 挂载点。
- 解析 `VID_*.insv` 文件名。
- 聚合跨卡同步 sequence。
- 输出 GUI 可直接消费的数据结构。

交付文件：

- `apps/insta_batch_export/core/media_scan.py`
- `apps/insta_batch_export/core/sequence_grouping.py`
- `apps/insta_batch_export/tests/test_media_scan.py`
- `apps/insta_batch_export/tests/test_sequence_grouping.py`

验收标准：

- 能识别当前 5 个 SD 卡挂载点。
- 能解析 `VID_20260521_191237_00_006.insv` 为 timestamp 和 seq id。
- 对不同卡 seq id 不一致但 timestamp 接近的文件，能聚合为同一个 sequence。
- 对缺失某个 pos 的 sequence，能标记为不完整而不是静默丢弃。

### Subagent 3：Python GUI

职责：

- 实现 PySide6 GUI。
- 提供 SD 卡到 pos 的绑定。
- 展示 sequence table。
- 支持连续选择、输出目录选择、overwrite 开关。
- 显示导出任务状态和日志入口。

交付文件：

- `apps/insta_batch_export/gui_app.py`
- `apps/insta_batch_export/core/config_store.py`
- `apps/insta_batch_export/README.md`
- `apps/insta_batch_export/requirements.txt`

验收标准：

- 启动后能列出 5 个挂载点。
- 5 个 pos 下拉绑定互斥。
- 未完成 5 个 pos 绑定时，导出按钮禁用。
- sequence table 能显示完整性状态和每个 pos 对应文件。
- 用户选择输出目录和 sequence 后能生成任务队列。

### Subagent 4：export job orchestration 和日志/manifest

职责：

- 实现任务队列。
- 按 `max_parallel_exports` 调用 C++ exporter；默认串行，允许用户调高并发。
- 捕获 stdout/stderr。
- 写 log 和 manifest。
- 支持 skip/overwrite。

交付文件：

- `apps/insta_batch_export/core/export_jobs.py`
- `apps/insta_batch_export/tests/test_export_jobs.py`
- GUI 中的 worker thread/process 调用 glue。

验收标准：

- 已存在输出且 overwrite=false 时任务 skipped。
- exporter 返回 0 时任务 done，并记录 manifest。
- exporter 返回非 0 时任务 failed，日志包含命令、返回码、stdout/stderr。
- 同时运行的 exporter 进程数不超过 `max_parallel_exports`。
- GUI 在导出过程中不阻塞，可以实时更新进度。

### 主 session 集成职责

主 session 不做大块实现，负责：

- 审核四个 subagent 的边界是否冲突。
- 合并文件结构和调用协议。
- 运行端到端 smoke test。
- 检查文档是否和真实命令一致。
- 最终给出残余风险和下一步实验建议。

## 端到端验收标准

批准实施后，最终版本需要满足：

1. `source ./env.sh` 后可构建 exporter。
2. GPU smoke check 能确认 exporter 默认调用 `EnableCuda(true)`；如果当前机器 CUDA/NVML 状态异常，文档记录失败原因和 CPU fallback 命令。
3. GUI 可启动并扫描 `/media/vox`。
4. 用户能把 5 张卡分别绑定到 5 个 pos。
5. GUI 能按 pos 显示最近 N 个视频，并支持逐 cell 手动选择。
6. 点击导出后，输出结构为：

```text
<output_dir>/<pos>/<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4
```

7. 导出参数固定为：

```text
output_size=3840x1920
enable_flowstate=true
enable_denoise=true
enable_directionlock=false
```

8. 输出根目录下生成：

```text
export_manifest.jsonl
export_logs/
```

9. 单个任务失败不会中断整个批次，GUI 显示 failed 并继续处理后续任务。
10. GUI 支持设置 `max_parallel_exports`；验收时至少验证 `1` 和 `2` 两种并发限制。
11. README 记录安装、启动、导出、日志位置和已知限制。

## 主要风险

### MediaSDK 对单个 `.insv` 的输入格式要求

已确认业务输入粒度是单个 `.insv` 对应一个相机的完整全景视频。仍需在实施第一步用真实 `.insv` 做最小导出实验，验证 MediaSDK 对该文件的编码、相机型号、metadata 和模型路径没有额外要求。

### 4K panorama 定义

已确认 4K panorama 为 `3840x1920`。

### 时间同步和 sequence 对齐

当前文件名显示不同卡之间可能存在分钟级或秒级差异，也可能存在旧素材混在卡里。第一版使用时间窗口聚类，并在 GUI 中显式显示每个 pos 的匹配文件，让用户人工确认，不做静默自动对齐。

### GUI 依赖

PySide6 可能需要安装 Python 包。实施前应确认是否使用当前系统 Python、conda env，还是创建专用 conda env。默认建议创建专用 conda env，避免污染系统环境。

### 当前本机 GPU runtime 状态

当前本机有一张 RTX 4090，但 `nvidia-smi` 报 `Driver/library version mismatch`。实施时需要先做最小 CUDA/MediaSDK GPU 导出 smoke test；如果失败，优先处理驱动用户态库和内核模块版本不一致的问题。这个问题不影响文件扫描、GUI 和 CPU fallback 设计，但会影响 GPU 导出验证。

已做的 smoke test 结论：

- `./build/media_sdk_demo` 能读取真实 X4 `.insv`、解析 metadata、识别双视频流、加载 gyro/stabilization 信息。
- GPU 路径失败于 CUDA 初始化：`CUDA_ERROR_SYSTEM_DRIVER_MISMATCH: system has unsupported display driver / cuda driver combination`。
- `-disable_cuda -image_processing_accel cpu -enable_soft_decode` 仍会 core dump，因为 MediaSDK stitching/render 仍需要 offscreen EGL/OpenGL。
- 强制 Mesa software EGL 失败：`Not allowed to force software rendering when API explicitly selects a hardware device`。
- 因此当前本机要做真实 MediaSDK 导出，需要先修复 NVIDIA kernel module 与用户态库版本不一致问题。当前证据：kernel module `595.58.03`，NVML/user-space library `595.71`。

## 实施顺序

1. 先验证 MediaSDK 对真实 `.insv` 的最小导出命令。
2. 开发 C++ exporter CLI。
3. 开发扫描和 grouping core，并用当前 `/media/vox` 文件结构写测试。
4. 开发 export job queue。
5. 开发 GUI。
6. GPU smoke test：先跑 1 个任务，再跑 `max_parallel_exports=2` 的小批次。
7. 端到端 smoke test：选择 1 个 sequence、5 个 pos、输出到临时目录。
8. 文档更新。

## 已确认需求

用户已确认：

1. 4K 全景按 `3840x1920`。
2. 一个 `.insv` 就是一个相机的完整全景视频输入。
3. 输出文件名接受 `<YYYYMMDD_HHMMSS>_<mount_id>_<source_seq_id>.mp4`。
4. 默认严格只导出 5/5 完整 sequence。
5. 使用单 GPU；GUI 支持把并发任务数从默认 `1` 调高，用独立 exporter 进程共享同一张 GPU。
