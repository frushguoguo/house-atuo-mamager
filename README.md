# house-atuo-mamager

基于 `IMPLEMENTATION_PLAN.md` 的首版落地实现（P0/P1 最小闭环）：

- 数据抓取（贝壳/链家/安居客模拟采集器）
- 数据清洗（标准化与去重）
- 热点分析（区域、价格区间、小区热度）
- 文案生成（多版本宣传文案）
- 统一 pipeline CLI（支持按任务执行）
- OpenClaw 接入桥接入口（任务名映射）

## 快速开始

```powershell
cd D:\111\house-atuo-mamager
python -m property_workflow.orchestration.pipeline --task full --config .\property-workflow-config.yaml
```

运行产物写入 `runtime\YYYYMMDD\` 目录：

- `raw_listings.json`
- `clean_listings.json`
- `analysis_report.json`
- `analysis_report.md`
- `copywriting.json`

## 视频任务增强（阶段D）

```powershell
python -m property_workflow.orchestration.pipeline --task video --config .\property-workflow-config.yaml
```

- 支持字幕烧录（基于 `video_captions.srt`）。
- 支持模板滤镜（`video_template`: `default` / `clean`）。
- 支持可选 BGM（配置 `content_generation.video_bgm_path`）。
- 支持 BGM 音量（配置 `content_generation.video_bgm_volume`，范围 `0.0~1.0`）。

## OpenClaw 接入方式

```powershell
python -m property_workflow.integrations.openclaw.task_runner --task full --config .\property-workflow-config.yaml
```

可用任务：`collect` `clean` `analyze` `copywrite` `video` `publish` `full`


## A+ Unattended

```powershell
cd D:\111\house-atuo-mamager
python .\scripts\aplus_endpoint_finder.py
python .\scripts\aplus_unattended_daemon.py --config .\property-workflow-config.yaml --collect-task collect
```

See also: `docs/APLUS_UNATTENDED.md`

