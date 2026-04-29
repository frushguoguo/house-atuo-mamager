# A+ 无人值守模式

## 目标
- 定时刷新 A+ 授权状态（cookies + keepalive）
- 定时从 A+ 安装包和本地存储中发现房源接口候选 URL
- 可选定时触发 `collect/full` 任务

## 1. 先跑接口发现（从 A+ 包自动提取）
```powershell
cd D:\111\house-atuo-mamager
python .\scripts\aplus_endpoint_finder.py
```

输出：
- `runtime\aplus_endpoint_discovery.json`

该文件会被 `desktop_aplus` 自动探测逻辑读取并加入候选接口池。

## 2. 启动无人值守守护
```powershell
cd D:\111\house-atuo-mamager
python .\scripts\aplus_unattended_daemon.py --config .\property-workflow-config.yaml --collect-task collect
```

默认行为：
- 每 `300s` 刷授权状态（输出 `runtime\aplus_auth_state.json`）
- 每 `1800s` 刷接口发现（输出 `runtime\aplus_endpoint_discovery.json`）
- 每 `1800s` 执行一次 `collect`

## 3. PowerShell 一键启动
```powershell
cd D:\111\house-atuo-mamager
.\scripts\run_aplus_unattended.ps1 -Config .\property-workflow-config.yaml -CollectTask collect
```

## 4. 关键输出文件
- `runtime\aplus_auth_state.json`：授权刷新快照
- `runtime\aplus_endpoint_discovery.json`：从 A+ 包 + 本地存储发现的候选接口
- `runtime\aplus_auto_probe_result.json`：采集器自动探测接口的尝试结果
- `runtime\YYYYMMDD\raw_listings.json`：采集结果
