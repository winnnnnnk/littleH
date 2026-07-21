[CmdletBinding()]
param([switch]$Runtime)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script = Join-Path $Root "plugins\xiaoh\scripts\xiaoh.py"
$Arguments = @($Script, "doctor")
if ($Runtime) { $Arguments += "--runtime" }

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
if ($py) { & $py.Source -3 @Arguments }
elseif ($python) { & $python.Source @Arguments }
else { throw "缺少Python 3" }
if ($LASTEXITCODE -ne 0) { throw "小H检查失败" }
