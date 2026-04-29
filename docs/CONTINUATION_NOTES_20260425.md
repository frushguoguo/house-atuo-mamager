# Continuation Notes - 2026-04-25

## User intent
- 用户要求继续 A+ 抓包 -> 自动探测 -> 接入真实房源接口采集链路。
- 当前目标是让 `desktop_aplus auto probe` 成功命中真实列表接口，不再回退模拟数据。

## What has been done
1. 已完成 `20260425` 的 `clean -> analyze -> copywrite` 补跑，产物齐全。
2. 多次抓包与探测执行完成，旧抓包曾仅命中壳页请求（`welcome/ping`）。
3. 已修复抓包脚本：
   - `scripts/aplus_cdp_capture.js`
   - 由仅抓 `page` 改为抓 `page + webview`
   - 支持多 target 并行抓取
   - 增加响应体抓取（`responses` 字段）
4. 已修复启动脚本：
   - `scripts/run_aplus_cdp_capture.ps1`
   - 固定输出到 `D:\111\house-atuo-mamager\runtime\aplus_click_capture.json`
   - 增加 CDP 端口就绪等待
5. 已调整自动探测评分逻辑：
   - `property_workflow/collectors/aplus_desktop.py`
   - 提高 `/new/api/deal/*` 等路径权重

## Current blocker
- 最近一次本地自动重跑时，`http://127.0.0.1:9222/json/list` 未就绪（端口未拉起），导致抓包流程中断。
- 需要用户在管理员窗口重新拉起脚本并提供最后一行输出确认。

## Exact next command
```powershell
cd D:\111\house-atuo-mamager
.\scripts\run_aplus_cdp_capture.ps1 -DebugPort 9222 -Seconds 240 -ForceRestart
```

## What to send back
- 仅需回传命令最后一行（应包含）：
  - `done: hits=..., responses=... -> D:\111\house-atuo-mamager\runtime\aplus_click_capture.json`

## Immediate next step after receiving output
1. 读取最新 `runtime/aplus_click_capture.json`
2. 从 `responses` 中提取可用列表接口与响应路径（如 `data.list`/`rows` 等）
3. 写入 `desktop_aplus` 探测候选并重跑 `aplus_bootstrap_collect`
4. 验证 Beike 数据来自真实接口（非 synthetic fallback）

## 2026-04-26 Development Update (Phase-2)
- 已完成“跳过现场验证”的开发阶段改造，核心目标是降低对 Python 直连内网接口的依赖。

### New capabilities
1. CDP 抓包增强
- 支持抓取 `webview`（不再仅 `page`）
- 支持多 target 并行抓取
- 支持 `Network.getResponseBody`，并在 `responses` 中输出：`jsonKeys`、`listPath`、`dictRowCount`、`listRows`

2. 探测候选自动注入
- `aplus_endpoint_discovery` 现可解析 `aplus_click_capture.json` 中 `requests/responses`
- 自动生成 `direct_candidates`（含 page 参数、base_params、response_path）并并入 `endpoint_candidates`
- `aplus_endpoint_finder` 和 `aplus_unattended_daemon` 均自动纳入 click capture 文件

3. 采集侧回灌降级
- `aplus_desktop` 新增 CDP 回灌兜底：auto probe 失败时，尝试从 `runtime/aplus_click_capture.json` 的 `responses.listRows` 直接映射房源
- 仅在命中房源业务 URL 时启用，避免误用 IM 数据

### Current status
- auto probe 已能尝试 `house.link` 的 `/search/searchQueryNew` 与 `/pc/risk/getRiskInfoV3`，但当前 Python 直连仍超时。
- 待后续验证时，若抓包含房源 `responses.listRows`，可走“CDP 回灌兜底”产出真实行数据。

### Next verification step
1. 重新执行 CDP 抓包（确保房源页面有翻页/筛选/详情操作）
2. 检查 `runtime/aplus_click_capture.json` 中：
   - `response_hits > 0`
   - `responses[*].dictRowCount > 0` 且 URL 命中 `house.link` / `search` / `deal` / `house`
3. 运行 `aplus_bootstrap_collect.py`，观察是否出现：
   - `[beike][desktop] auto probe failed, fallback to CDP capture rows: ...`

## 2026-04-26 P2 Step-1 Delivered
- Added `video` task to pipeline and OpenClaw bridge.
- New module: `property_workflow/content/video_generator.py`.
- Outputs:
  - `video_storyboard.json`
  - `video_captions.srt`
  - `video_generation_report.json`
  - `promo_video.mp4` (when FFmpeg exists)
- Current runtime check (`20260425`) status:
  - `video_generation_report.json` => `skipped_ffmpeg_missing`

### Run command
```powershell
python -m property_workflow.orchestration.pipeline --task video --config .\property-workflow-config.yaml --date 20260425
```

## 2026-04-26 P2 Step-2 Delivered
- Added unified publish engine with platform adapter abstraction and local mock publishers.
- New package:
  - `property_workflow/publishing/base.py`
  - `property_workflow/publishing/mock_publishers.py`
  - `property_workflow/publishing/engine.py`
  - `property_workflow/publishing/__init__.py`

### Pipeline integration
- Added `publish` task in:
  - `property_workflow/orchestration/pipeline.py`
  - `property_workflow/integrations/openclaw/task_runner.py`
- New publish artifacts under `runtime/<date>/`:
  - `publish_payload.json`
  - `publish_report.json`
  - `publish_records_<platform>.json` (when platform enabled)

### Validation
1. Syntax check passed:
```powershell
python -m py_compile property_workflow\publishing\base.py property_workflow\publishing\mock_publishers.py property_workflow\publishing\engine.py property_workflow\orchestration\pipeline.py property_workflow\integrations\openclaw\task_runner.py tests\test_publish_pipeline.py
```
2. Pipeline publish smoke (using project config):
```powershell
python -m property_workflow.orchestration.pipeline --task publish --config .\property-workflow-config.yaml --date 20260425
```
Result: `status=skipped_no_enabled_platforms` (expected; all platforms disabled in config).
3. Positive mock publish check (temporary inline config, no file changes):
- `status=success`
- generated:
  - `runtime\20260425\publish_records_douyin.json`
  - `runtime\20260425\publish_records_xiaohongshu.json`

### Test status
- Added `tests/test_publish_pipeline.py`.
- `pytest` is currently unavailable in environment (`No module named pytest`), so test suite was not executed.
