param(
  [string]$Profile = "safe_demo",
  [int]$Port = 8010
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
python (Join-Path $Root "scripts\run_stable_smoke.py") --profile $Profile --port $Port
exit $LASTEXITCODE

