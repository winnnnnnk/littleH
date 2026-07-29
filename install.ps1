[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CodexTarget = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { Join-Path $HOME ".codex" } else { $env:CODEX_HOME }
$Script = Join-Path $Root "plugins\xiaoh\scripts\xiaoh.py"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) { throw "缺少必需命令: codex" }
New-Item -ItemType Directory -Path $CodexTarget -Force | Out-Null

& codex plugin marketplace add $Root --json
if ($LASTEXITCODE -ne 0) { throw "添加xiaoh Marketplace失败" }
& codex plugin add xiaoh@xiaoh --json
if ($LASTEXITCODE -ne 0) { throw "安装xiaoh Plugin失败" }

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if ($py) { & $py.Source -3 $Script setup --allow-degraded }
elseif ($python) { & $python.Source $Script setup --allow-degraded }
else { throw "缺少Python 3" }
if ($LASTEXITCODE -ne 0) { throw "初始化xiaoh运行环境失败" }
