# AI Limits Panel launcher (Windows PowerShell 5.1+)
param(
    [switch]$Watch,
    [switch]$All,
    [switch]$Json,
    [int]$Interval = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $Root

$pyArgs = @("limits.py")
if ($Watch) { $pyArgs += "--watch" }
if ($All) { $pyArgs += "--all" }
if ($Json) { $pyArgs += "--json" }
if ($Interval -gt 0) { $pyArgs += @("--interval", "$Interval") }

& python @pyArgs
exit $LASTEXITCODE
