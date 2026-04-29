param(
  [int]$DebugPort = 9222,
  [int]$Seconds = 180,
  [string]$AplusExe = "$env:APPDATA\A+\A+.exe",
  [switch]$ForceRestart
)

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutputPath = Join-Path $ProjectRoot "runtime\aplus_click_capture.json"

if ($ForceRestart) {
  Get-Process -Name "A+" -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Seconds 1
}

if (!(Test-Path -LiteralPath $AplusExe)) {
  throw "A+ exe not found: $AplusExe"
}

Write-Host "[aplus-cdp] launch A+ with remote debugging port $DebugPort"
Start-Process -FilePath $AplusExe -ArgumentList "--remote-debugging-port=$DebugPort"

$ready = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$DebugPort/json/list" -TimeoutSec 2
    $ready = $true
    break
  } catch {
  }
}
if (-not $ready) {
  throw "CDP endpoint not ready: http://127.0.0.1:$DebugPort/json/list"
}

Write-Host "[aplus-cdp] output -> $OutputPath"
node "$PSScriptRoot\aplus_cdp_capture.js" --port $DebugPort --seconds $Seconds --output $OutputPath
