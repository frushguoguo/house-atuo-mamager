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

可用任务：`collect` `clean` `analyze` `copywrite` `video` `publish` `aplus_sync` `full`

`aplus_sync` 用于将 `clean_listings.json` 同步到 A+ 状态仓（当前为本地可验证闭环）：

```powershell
python -m property_workflow.orchestration.pipeline --task aplus_sync --config .\property-workflow-config.yaml --date 20260429_douyin_flowtest
```

## 多平台真实发布接入（sau_cli）

当前项目已支持在 `publish` 阶段调用 `social-auto-upload` 的 CLI（抖音/快手/小红书）。

1. 在 `property-workflow-config.yaml` 里配置平台：
- `publish_platforms[].publisher: "sau_cli"`
- `publish_platforms[].account: "<你的账号名>"`
- `publish_platforms[].sau_project_root: "D:/111/social-auto-upload"`
- `publish_platforms[].dry_run: true`（先演练）

2. 先跑演练（不真实发布）：

```powershell
python -m property_workflow.orchestration.pipeline --task publish --config .\property-workflow-config.yaml
```

3. 检查 `runtime\YYYYMMDD\publish_sau_result_<platform>_*.json` 的命令与参数。

4. 确认无误后把对应平台 `dry_run` 改为 `false`，再执行 `publish` 即可真实上传。

## 商业版任务链（新增）

新增任务：`comments` `private_domain` `crm_sync` `operations` `commercial_full`

商业版一键任务：

```powershell
python -m property_workflow.orchestration.pipeline --task commercial_full --config .\property-workflow-config.yaml
```

`commercial_full` 执行链路：

- `collect -> clean -> analyze -> copywrite -> video -> publish -> aplus_sync`
- `comments`（评论监控与自动回复建议）
- `private_domain`（线索评分、意向阶段、跟进策略）
- `crm_sync`（线索入库与增量同步）
- `operations`（运行体检、校验和、审计日志）

主要新增产物：

- `comment_moderation.json` `comment_replies.json` `comment_leads.json` `comments_report.json`
- `private_domain_profiles.json` `private_domain_followups.json` `private_domain_report.json`
- `crm_sync_actions.json` `crm_sync_conflicts.json` `crm_sync_report.json`
- `operations_report.json`
- `runtime\audit_log.jsonl`


## A+ Unattended

```powershell
cd D:\111\house-atuo-mamager
python .\scripts\aplus_endpoint_finder.py
python .\scripts\aplus_unattended_daemon.py --config .\property-workflow-config.yaml --collect-task collect
```

See also: `docs/APLUS_UNATTENDED.md`

