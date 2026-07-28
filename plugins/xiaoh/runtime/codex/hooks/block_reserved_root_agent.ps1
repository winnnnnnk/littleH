[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$Prepare,
    [switch]$SubagentStart,
    [switch]$SubagentStop,
    [string]$Config
)

$ErrorActionPreference = "Stop"
$hook = Join-Path $PSScriptRoot "block_reserved_root_agent.py"
if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
    throw "缺少Python委派Hook：$hook"
}

$arguments = @($hook)
if (-not [string]::IsNullOrWhiteSpace($Config)) {
    $arguments += @("--config", $Config)
}
if ($SelfTest) { $arguments += "--self-test" }
elseif ($Prepare) { $arguments += "--prepare" }
elseif ($SubagentStart) { $arguments += "--subagent-start" }
elseif ($SubagentStop) { $arguments += "--subagent-stop" }

if (-not [string]::IsNullOrWhiteSpace($env:PYTHON)) {
    & $env:PYTHON @arguments
}
elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @arguments
}
else {
    & python @arguments
}
exit $LASTEXITCODE
