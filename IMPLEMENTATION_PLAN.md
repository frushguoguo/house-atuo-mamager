# OpenClaw 房产无人值守系统落地实施计划

## 1. 目标与范围
- 目标：按文档《原生态OpenClaw房产无人值守工作流系统》完成可执行落地路线。
- 范围：先完成 P0/P1 可运行闭环（抓取 -> 清洗 -> 分析 -> 文案 -> 调度），再扩展 P2-P4。
- 主开发语言：`Python 3.10+`（文档明确用于数据处理、脚本执行、分析与自动化）。
- 运行与编排：`Node.js 20+`（OpenClaw 运行时、PM2、技能生态）。

## 2. 技术选型（严格对应文档）
- Python：`pandas` `numpy` `scikit-learn` `matplotlib` `plotly` `selenium` `requests` `beautifulsoup4` `pytesseract` `cryptography`。
- OpenClaw/ClawHub 技能：`agent-browser` `cron-job` `memory-manager` `tavily-search` `brave-search` `multi-search-engine` `ontology` `openai-whisper` `skill-vetter` 等。
- 系统依赖：`Git` `Docker` `FFmpeg` `PM2`。

## 3. 分阶段实施（P0 -> P4）

### 阶段 A：基础搭建（P0，必须先完成）
1. 环境安装与版本校验
- 安装 Node.js/Python3/Git/Docker/FFmpeg/PM2。
- 验收：`node --version` >= 20.x；`python --version` >= 3.10。

2. OpenClaw 核心能力启用
- 启用：`agent-browser`、`cron-job`、`memory-manager`。
- 验收：
  - Agent Browser 可打开页面并抓取字段；
  - Cron 可按表达式触发；
  - Memory 可保存与恢复任务上下文。

3. 项目骨架初始化（Python）
- 建立模块：`collectors/` `cleaning/` `analysis/` `content/` `orchestration/` `integrations/openclaw/` `config/`。
- 验收：可运行空管道命令 `python -m orchestration.pipeline --dry-run`。

### 阶段 B：核心能力（P1）
1. 数据抓取器（贝壳/链家/安居客）
- 先做统一采集接口，再实现各站适配器。
- 输入：搜索条件、区域、页数。
- 输出：标准化 `raw listings`（JSON/CSV）。
- 验收：每个平台稳定抓取 >= 100 条样本且字段齐全率 >= 95%。

2. 数据清洗器
- 规则：字段规范化、去重、缺失值处理、格式转换。
- 输出：`clean listings`。
- 验收：重复率下降、关键字段（价格/面积/区域/户型）完整率 >= 98%。

3. 热点分析引擎（Python）
- 能力：区域热度、小区热度、价格区间热度、差价分析。
- 输出：分析结果 + 图表。
- 验收：可生成日报（CSV + PNG/HTML 图表）。

4. 文案生成器（先文本，后多模态）
- 能力：房源亮点、话术、多版本文案。
- 验收：给定房源样本可自动生成 3 套文案模板。

### 阶段 C：扩展能力（P2）
1. 视频生成器
- 集成 FFmpeg，支持模板化剪辑与字幕。
- 验收：输入素材可自动输出短视频成片。

2. 多平台发布引擎
- 对接抖音/小红书/快手/视频号（先预留接口，逐个平台上线）。
- 验收：至少 1 个平台实现自动发布成功。

3. 贝壳 A+ 后台自动化
- RPA + Agent Browser：登录、录入、调价、上下架、日志留痕。
- 验收：完成一条房源从抓取到 A+ 后台入库闭环。

### 阶段 D：高级能力（P3）
1. 评论自动运营
- 评论监控、关键词过滤、智能回复。
- 验收：自动回复命中率与人工可接受率达标。

2. 私域自动转化
- 微信自动回复、线索打标、跟进策略。
- 验收：线索状态自动流转可追踪。

3. 心理学分析引擎
- 意向判断、成交概率评估、推荐话术。
- 验收：输出结构化画像与策略建议。

### 阶段 E：优化完善（P3/P4）
1. 知识图谱与长期记忆
- 建立房源/客户/行为关系图谱，沉淀经验模板。
- 验收：支持关系检索与历史决策复用。

2. 运维与安全
- 健康检查、自动重启、备份、审计日志、数据加密。
- 验收：故障自动恢复，关键操作可追溯。

3. 批量部署
- Docker 化 + 环境参数化。
- 验收：新环境一键拉起核心流程。

## 4. 模块依赖与开发顺序
1. 底层核心层（OpenClaw Runtime / Scheduler / Memory）
2. 数据采集层（抓取与清洗）
3. 业务引擎层（分析、生成、发布、自动化）
4. AI 增强层（心理分析、自进化、知识图谱）
5. 终端输出层（平台发布、私域触达、A+后台）

## 5. 里程碑与交付物
- M1（P0）：环境+技能+骨架完成。
- M2（P1）：抓取/清洗/分析/文案闭环。
- M3（P2）：视频+发布+A+自动化最小可用。
- M4（P3）：评论运营+私域转化+心理分析。
- M5（P4）：知识沉淀+安全运维+批量部署。

## 6. OpenClaw 接入方案（开发完成后）
1. 将 Python 能力封装为可调用命令
- 统一 CLI：`python -m orchestration.pipeline --task <task_name> --config property-workflow-config.yaml`。

2. 在 OpenClaw 中注册工作流任务
- 定义任务：`collect` `clean` `analyze` `generate` `publish` `beike_sync`。
- 由 `cron-job` 触发定时任务，由 `memory-manager` 保存上下文。

3. 通过 Agent Browser/RPA 接入网页与后台
- 抓取端：房产站点列表页+详情页。
- 执行端：贝壳 A+ 后台自动录入与状态同步。

4. 接入可观测性与审计
- 每次任务输出结构化日志（任务ID、输入摘要、结果、异常）。
- 审计日志单独存档，配合加密存储。

5. 灰度上线流程
- 先单城市/单账号/单平台灰度。
- 达到稳定阈值后再扩展到多城市多账号。

## 7. 近期执行清单（建议本周）
1. 完成 P0 所有环境与技能安装验证。
2. 完成 `collect -> clean -> analyze -> copywriting` 最小链路。
3. 形成第一版 `property-workflow-config.yaml` 并跑通定时任务。
4. 接入贝壳 A+ 登录与单条房源录入（最小闭环）。
