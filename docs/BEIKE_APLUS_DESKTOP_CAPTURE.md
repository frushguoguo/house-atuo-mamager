# 贝壳 A+ 桌面版房源抓取落地说明

## 1. 当前实现状态
- 已接入 `BeikeCollector -> desktop_aplus` 实采集模式。
- 默认仍是模拟数据；配置 `desktop_aplus.enabled=true` 后切换到真实抓取。
- 实采集逻辑：
  - 从 `A+` 桌面端本地 `Cookies` 读取会话。
  - 复用会话调用你配置的房源列表 API。
  - 映射为统一标准字段（listing_id、面积、总价、标签等）。

## 2. 你需要补齐的最小信息
- `list_endpoint`：房源列表请求 URL。
- `list_method`：通常 `POST`。
- `list_base_params` 与 `list_json_body`：固定查询参数。
- `list_page_param` / `list_page_size_param`：分页字段名。
- `list_response_path`：列表数组在响应里的路径。
- `field_mapping`：接口字段到标准字段映射（已给默认候选，可按实际调整）。

## 3. 推荐抓取方式（桌面扫码登录场景）
1. 在 A+ 客户端保持登录状态。
2. 先验证本地会话是否可读：
```powershell
cd D:\111\house-atuo-mamager
python -m property_workflow.collectors.aplus_probe
```
3. 如果能看到多个 cookie 名称，再进入下一步。
4. 进入 `房源 -> 全部房源`，切分页并触发一次搜索。
5. 用抓包工具记录该次请求（建议 Charles/Fiddler/mitmproxy 任一）。
6. 将以下信息填入 `property-workflow-config.yaml`：
- URL、Method、分页参数、固定过滤参数。
- 响应 JSON 中列表数组路径。
7. 执行：
```powershell
cd D:\111\house-atuo-mamager
python -m property_workflow.orchestration.pipeline --task collect --config .\property-workflow-config.yaml
```
8. 结果写入：
- `runtime\YYYYMMDD\raw_listings.json`

## 4. 如果你要“我生成二维码，你扫码”
1. 启动本地二维码页（会调用 A+ 同款 PassportSDK）：
```powershell
cd D:\111\house-atuo-mamager
python .\scripts\aplus_qr_login_server.py
```
2. 浏览器打开 `http://127.0.0.1:18765/`，你扫码并手机确认。
3. 成功后会落盘：
- `runtime\aplus_qr_login_result.json`
4. 用 serviceTicket 换取 SAAS 会话 Cookie：
```powershell
python .\scripts\aplus_ticket_exchange.py
```
5. Cookie 将落盘到：
- `runtime\aplus_session_cookies.json`

## 5. OpenClaw 接入方式
- OpenClaw 继续调用原桥接入口即可：
```powershell
python -m property_workflow.integrations.openclaw.task_runner --task collect --config .\property-workflow-config.yaml
```
- `collect` 成功后，后续 `clean/analyze/copywrite/full` 不需要改调用方式。

## 6. 安全与合规
- 仅用于你有权限的数据账号。
- 不要外传 Cookie、Token、扫码二维码截图。
- 生产环境建议加白名单与审计日志。
