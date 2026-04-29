param(
  [string]$Config = ".\property-workflow-config.yaml",
  [int]$AuthInterval = 300,
  [int]$DiscoveryInterval = 1800,
  [string]$CollectTask = "collect",
  [int]$CollectInterval = 1800
)

python .\scripts\aplus_unattended_daemon.py `
  --config $Config `
  --auth-interval $AuthInterval `
  --discovery-interval $DiscoveryInterval `
  --collect-task $CollectTask `
  --collect-interval $CollectInterval
