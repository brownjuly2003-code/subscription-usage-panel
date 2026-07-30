# Fetch subscription remaining + open Grafana-style HTML
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root
& python limits.py --html --open
exit $LASTEXITCODE
