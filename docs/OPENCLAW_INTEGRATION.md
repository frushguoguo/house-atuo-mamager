# OpenClaw 接入说明

## 1. 统一执行入口

```bash
python -m property_workflow.integrations.openclaw.task_runner --task full --config ./property-workflow-config.yaml
```

可选任务：

- `collect`
- `clean`
- `analyze`
- `copywrite`
- `video`
- `publish`
- `full`

## 2. 任务映射建议

- `collect` -> 数据采集
- `clean` -> 数据清洗
- `analyze` -> 热点分析
- `copywrite` -> 文案生成
- `video` -> 视频分镜与成片生成（有 FFmpeg 时输出 `promo_video.mp4`）
- `publish` -> 多平台发布引擎（当前为本地 mock 平台适配器）
- `full` -> `collect -> clean -> analyze -> copywrite`

## 3. 调度建议

- 每日 08:00：`full`
- 每日 08:10：`video`
- 每日 08:15：`publish`
- 每日 12:00 / 18:00：`collect + clean + analyze`

## 4. 任务产物

基础产物：

- `raw_listings.json`
- `clean_listings.json`
- `analysis_report.json`
- `analysis_report.md`
- `copywriting.json`

视频任务产物：

- `video_storyboard.json`
- `video_captions.srt`
- `video_generation_report.json`
- `promo_video.mp4`（仅在 FFmpeg 可用时生成）

发布任务产物：

- `publish_payload.json`
- `publish_report.json`
- `publish_records_<platform>.json`（例如 `publish_records_douyin.json`）
