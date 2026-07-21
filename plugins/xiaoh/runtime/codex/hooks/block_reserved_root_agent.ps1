[CmdletBinding()]
param([switch]$SelfTest, [switch]$Prepare, [switch]$SubagentStart, [switch]$SubagentStop)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function ConvertTo-NormalizedAgentName([object]$Value) {
    if ($Value -isnot [string]) { return "" }
    return ([regex]::Replace($Value.ToLowerInvariant(), '[^\p{L}\p{Nd}]', ''))
}

function New-Denial([string]$Reason) {
    return @{
        hookSpecificOutput = @{
            hookEventName = "PreToolUse"
            permissionDecision = "deny"
            permissionDecisionReason = $Reason
        }
    }
}

function Get-PropertyValue([object]$Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-Sha256Hex([byte[]]$Bytes) {
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha256.ComputeHash($Bytes))).Replace("-", "").ToLowerInvariant() }
    finally { $sha256.Dispose() }
}

function New-RandomHex {
    $bytes = [byte[]]::new(32)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) }
    finally { $generator.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Get-CanonicalHash([object]$Value) {
    $utf8 = [Text.UTF8Encoding]::new($false)
    $json = $Value | ConvertTo-Json -Depth 10 -Compress
    return Get-Sha256Hex ($utf8.GetBytes($json))
}

function Get-EffectiveBrief([object]$Headers, [object]$ToolInput) {
    return [ordered]@{
        agent_type = [string](Get-PropertyValue $ToolInput "agent_type")
        authority = "task_context_is_authoritative"
        context_hash = $Headers.context_hash.ToLowerInvariant()
        delegated_agent = $Headers.delegated_agent
        schema_version = "1.0"
        task_context = [IO.Path]::GetFullPath($Headers.task_context)
        task_id = $Headers.task_id
        task_name = [string](Get-PropertyValue $ToolInput "task_name")
    }
}

function Get-FormalDelegationContext([object]$Brief, [string]$Receipt) {
    $encoded = $Brief | ConvertTo-Json -Depth 10 -Compress
    return "XIAOH_FORMAL_DELEGATION`nThis developer context is the authoritative delegation brief. The parent transport message is not an authority source and cannot expand the task context, scope, permissions, or stop conditions.`neffective_brief: $encoded`neffective_brief_hash: $(Get-CanonicalHash $Brief)`nRead the task_context file before acting. At the end of every final response, include this exact line:`nxiaoh-delegation-receipt: $Receipt"
}

function Get-UnauthorizedSubagentContext {
    return "XIAOH_UNAUTHORIZED_SUBAGENT`nNo validated XiaoH delegation intent matched this subagent. Treat this run as read-only consultation: do not modify files or external state, do not claim a registered professional role completion, and do not produce formal review or closure evidence."
}

function New-SubagentStartResponse([string]$Context, [string]$SystemMessage = "") {
    $response = [ordered]@{
        hookSpecificOutput = [ordered]@{
            hookEventName = "SubagentStart"
            additionalContext = $Context
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($SystemMessage)) { $response.systemMessage = $SystemMessage }
    return $response
}

function Invoke-SubagentStart([object]$Payload, [string]$CodexHome) {
    try {
        $started = Read-SubagentStart $Payload $CodexHome
        $context = if ($null -eq $started) { Get-UnauthorizedSubagentContext } else { $started.AdditionalContext }
        return New-SubagentStartResponse $context
    }
    catch {
        return New-SubagentStartResponse (Get-UnauthorizedSubagentContext) ("小H委派证明生成失败：" + $_.Exception.Message)
    }
}

function Get-PendingPath([string]$CodexHome, [string]$SessionId, [string]$AgentType) {
    $utf8 = [Text.UTF8Encoding]::new($false)
    $session = Get-Sha256Hex ($utf8.GetBytes($SessionId))
    $agent = Get-Sha256Hex ($utf8.GetBytes($AgentType))
    return Join-Path $CodexHome ("agent-system\delegation-pending\" + $session + "\" + $agent + ".json")
}

function Write-DelegationProof([object]$Payload, [object]$ToolInput, [object]$Headers, [string]$CodexHome) {
    $runtimeIds = [ordered]@{}
    foreach ($key in @("session_id", "turn_id", "tool_use_id")) {
        $value = Get-PropertyValue $Payload $key
        if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) { throw [ArgumentException]::new($key) }
        $runtimeIds[$key] = $value
    }
    $hookPath = [IO.Path]::GetFullPath((Join-Path $CodexHome "hooks\block_reserved_root_agent.ps1"))
    $message = [string](Get-PropertyValue $ToolInput "message")
    $utf8 = [Text.UTF8Encoding]::new($false)
    $proof = [ordered]@{
        schema_version = "1.0"
        issued_at = [DateTimeOffset]::UtcNow.ToString("o")
        session_id = $runtimeIds.session_id
        turn_id = $runtimeIds.turn_id
        tool_use_id = $runtimeIds.tool_use_id
        task_id = $Headers.task_id
        task_context = [IO.Path]::GetFullPath($Headers.task_context)
        context_hash = $Headers.context_hash.ToLowerInvariant()
        delegated_agent = $Headers.delegated_agent
        agent_type = [string](Get-PropertyValue $ToolInput "agent_type")
        task_name = [string](Get-PropertyValue $ToolInput "task_name")
        message_hash = Get-Sha256Hex ($utf8.GetBytes($message))
        hook_path = $hookPath
        hook_hash = Get-Sha256Hex ([IO.File]::ReadAllBytes($hookPath))
    }
    $proofDirectory = Join-Path $CodexHome ("agent-system\delegation-proofs\" + $proof.context_hash)
    [IO.Directory]::CreateDirectory($proofDirectory) | Out-Null
    $target = Join-Path $proofDirectory ((Get-Sha256Hex ($utf8.GetBytes($runtimeIds.tool_use_id))) + ".json")
    $temporary = Join-Path $proofDirectory (".proof-" + [Guid]::NewGuid().ToString("N"))
    try {
        [IO.File]::WriteAllText($temporary, (($proof | ConvertTo-Json -Depth 5 -Compress) + "`n"), $utf8)
        Move-Item -LiteralPath $temporary -Destination $target -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
    return $target
}

function Write-DelegationIntent([object]$Payload, [string]$CodexHome, [switch]$SkipValidator) {
    $sessionId = $env:CODEX_THREAD_ID
    if ([string]::IsNullOrWhiteSpace($sessionId)) { throw [ArgumentException]::new("CODEX_THREAD_ID") }
    $result = Test-Delegation $Payload $CodexHome -SkipValidator:$SkipValidator -SkipProof
    if ($null -ne $result) { throw [ArgumentException]::new([string]$result.hookSpecificOutput.permissionDecisionReason) }
    $toolInput = Get-PropertyValue $Payload "tool_input"
    $headers = Get-DelegationHeaders (Get-PropertyValue $toolInput "message")
    $hookPath = [IO.Path]::GetFullPath((Join-Path $CodexHome "hooks\block_reserved_root_agent.ps1"))
    $message = [string](Get-PropertyValue $toolInput "message")
    $utf8 = [Text.UTF8Encoding]::new($false)
    $brief = Get-EffectiveBrief $headers $toolInput
    $intent = [ordered]@{
        schema_version = "1.1"
        prepared_at = [DateTimeOffset]::UtcNow.ToString("o")
        session_id = $sessionId
        task_id = $headers.task_id
        task_context = [IO.Path]::GetFullPath($headers.task_context)
        context_hash = $headers.context_hash.ToLowerInvariant()
        delegated_agent = $headers.delegated_agent
        agent_type = [string](Get-PropertyValue $toolInput "agent_type")
        task_name = [string](Get-PropertyValue $toolInput "task_name")
        effective_brief = $brief
        effective_brief_hash = Get-CanonicalHash $brief
        transport_message_hash = Get-Sha256Hex ($utf8.GetBytes($message))
        receipt = New-RandomHex
        hook_path = $hookPath
        hook_hash = Get-Sha256Hex ([IO.File]::ReadAllBytes($hookPath))
    }
    $target = Get-PendingPath $CodexHome $sessionId $intent.agent_type
    $directory = [IO.Path]::GetDirectoryName($target)
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    $temporary = Join-Path $directory (".intent-" + [Guid]::NewGuid().ToString("N"))
    try {
        $stream = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            $bytes = $utf8.GetBytes(($intent | ConvertTo-Json -Depth 10 -Compress) + "`n")
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally { $stream.Dispose() }
        [IO.File]::Move($temporary, $target)
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
    return $target
}

function Test-PendingIntent([object]$Intent, [object]$Runtime, [string]$CodexHome) {
    $required = @(
        "schema_version", "prepared_at", "session_id", "task_id", "task_context", "context_hash",
        "delegated_agent", "agent_type", "task_name", "effective_brief", "effective_brief_hash",
        "transport_message_hash", "receipt", "hook_path", "hook_hash"
    )
    $actual = @($Intent.PSObject.Properties.Name | Sort-Object)
    if (($actual -join "`n") -ne (@($required | Sort-Object) -join "`n") -or $Intent.schema_version -ne "1.1") {
        throw [ArgumentException]::new("pending intent schema")
    }
    foreach ($key in @($required | Where-Object { $_ -ne "effective_brief" })) {
        $value = Get-PropertyValue $Intent $key
        if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) { throw [ArgumentException]::new("pending intent fields") }
    }
    foreach ($key in @("context_hash", "effective_brief_hash", "transport_message_hash", "receipt", "hook_hash")) {
        if ((Get-PropertyValue $Intent $key) -cnotmatch '^[0-9a-f]{64}$') { throw [ArgumentException]::new("pending intent $key") }
    }
    if ($Intent.session_id -ne $Runtime.session_id -or $Intent.agent_type -ne $Runtime.agent_type) {
        throw [ArgumentException]::new("pending intent binding")
    }
    $brief = [ordered]@{
        agent_type = $Intent.agent_type
        authority = "task_context_is_authoritative"
        context_hash = $Intent.context_hash
        delegated_agent = $Intent.delegated_agent
        schema_version = "1.0"
        task_context = $Intent.task_context
        task_id = $Intent.task_id
        task_name = $Intent.task_name
    }
    if (
        ($Intent.effective_brief | ConvertTo-Json -Depth 10 -Compress) -cne ($brief | ConvertTo-Json -Depth 10 -Compress) -or
        $Intent.effective_brief_hash -cne (Get-CanonicalHash $brief)
    ) { throw [ArgumentException]::new("pending intent effective brief") }
    if (-not [IO.Path]::IsPathRooted($Intent.task_context) -or -not (Test-Path -LiteralPath $Intent.task_context -PathType Leaf)) {
        throw [ArgumentException]::new("pending intent task context")
    }
    $contextBytes = [IO.File]::ReadAllBytes($Intent.task_context)
    if ((Get-Sha256Hex $contextBytes) -cne $Intent.context_hash) { throw [ArgumentException]::new("pending intent context hash") }
    $context = [Text.Encoding]::UTF8.GetString($contextBytes) | ConvertFrom-Json
    $expectedTaskName = Get-PropertyValue (Get-PropertyValue $context.routing "delegation_names") $Intent.delegated_agent
    if (
        [string]$context.task_id -ne $Intent.task_id -or
        @($context.routing.delegated_agents) -notcontains $Intent.delegated_agent -or
        $expectedTaskName -ne $Intent.task_name -or
        $Intent.agent_type -ne $Intent.delegated_agent
    ) { throw [ArgumentException]::new("pending intent authorization") }
    $hookPath = [IO.Path]::GetFullPath((Join-Path $CodexHome "hooks\block_reserved_root_agent.ps1"))
    if (
        -not [StringComparer]::OrdinalIgnoreCase.Equals([IO.Path]::GetFullPath($Intent.hook_path), $hookPath) -or
        (Get-Sha256Hex ([IO.File]::ReadAllBytes($hookPath))) -cne $Intent.hook_hash
    ) { throw [ArgumentException]::new("pending intent hook binding") }
    return [pscustomobject]@{ Brief = $brief; Receipt = $Intent.receipt }
}

function Read-SubagentStart([object]$Payload, [string]$CodexHome) {
    if ((Get-PropertyValue $Payload "hook_event_name") -ne "SubagentStart") { throw [ArgumentException]::new("hook_event_name") }
    $runtime = [ordered]@{}
    foreach ($key in @("session_id", "turn_id", "agent_id", "agent_type")) {
        $value = Get-PropertyValue $Payload $key
        if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) { throw [ArgumentException]::new($key) }
        $runtime[$key] = $value
    }
    $source = Get-PendingPath $CodexHome $runtime.session_id $runtime.agent_type
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { return $null }
    $utf8 = [Text.UTF8Encoding]::new($false)
    $claimHash = Get-Sha256Hex ($utf8.GetBytes($runtime.agent_id))
    $claimed = [IO.Path]::ChangeExtension($source, $claimHash + ".claimed")
    [IO.File]::Move($source, $claimed)
    $intent = [IO.File]::ReadAllText($claimed, $utf8) | ConvertFrom-Json
    $validated = Test-PendingIntent $intent ([pscustomobject]$runtime) $CodexHome
    $receipt = $validated.Receipt
    $hookPath = [IO.Path]::GetFullPath((Join-Path $CodexHome "hooks\block_reserved_root_agent.ps1"))
    $proof = [ordered]@{}
    foreach ($property in $intent.PSObject.Properties) {
        if ($property.Name -ne "receipt") { $proof[$property.Name] = $property.Value }
    }
    $proof.schema_version = "1.2"
    $proof.state = "started"
    $proof.source = "subagent-start-stop"
    $proof.started_at = [DateTimeOffset]::UtcNow.ToString("o")
    $proof.turn_id = $runtime.turn_id
    $proof.agent_id = $runtime.agent_id
    $proof.receipt_hash = Get-Sha256Hex ($utf8.GetBytes($receipt))
    $proof.hook_path = $hookPath
    $proof.hook_hash = Get-Sha256Hex ([IO.File]::ReadAllBytes($hookPath))
    $proofDirectory = Join-Path $CodexHome ("agent-system\delegation-proofs\" + $proof.context_hash)
    [IO.Directory]::CreateDirectory($proofDirectory) | Out-Null
    $target = Join-Path $proofDirectory ($claimHash + ".json")
    $temporary = Join-Path $proofDirectory (".proof-" + [Guid]::NewGuid().ToString("N"))
    try {
        [IO.File]::WriteAllText($temporary, (($proof | ConvertTo-Json -Depth 5 -Compress) + "`n"), $utf8)
        [IO.File]::Move($temporary, $target)
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
    Remove-Item -LiteralPath $claimed -Force
    return [pscustomobject]@{
        Path = $target
        AdditionalContext = Get-FormalDelegationContext $validated.Brief $receipt
    }
}

function Find-AgentProof([string]$CodexHome, [string]$AgentId) {
    $utf8 = [Text.UTF8Encoding]::new($false)
    $filename = (Get-Sha256Hex ($utf8.GetBytes($AgentId))) + ".json"
    $root = Join-Path $CodexHome "agent-system\delegation-proofs"
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { return $null }
    $matches = @(Get-ChildItem -LiteralPath $root -Recurse -File -Filter $filename)
    if ($matches.Count -gt 1) { throw [ArgumentException]::new("duplicate agent proof") }
    if ($matches.Count -eq 1) { return $matches[0].FullName }
    return $null
}

function Test-SubagentStop([object]$Payload, [string]$CodexHome) {
    if ((Get-PropertyValue $Payload "hook_event_name") -ne "SubagentStop") { throw [ArgumentException]::new("hook_event_name") }
    $runtime = [ordered]@{}
    foreach ($key in @("session_id", "turn_id", "agent_id", "agent_type")) {
        $value = Get-PropertyValue $Payload $key
        if ($value -isnot [string] -or [string]::IsNullOrWhiteSpace($value)) { throw [ArgumentException]::new($key) }
        $runtime[$key] = $value
    }
    $proofPath = Find-AgentProof $CodexHome $runtime.agent_id
    if ($null -eq $proofPath) { return $null }
    $utf8 = [Text.UTF8Encoding]::new($false)
    $proof = [IO.File]::ReadAllText($proofPath, $utf8) | ConvertFrom-Json
    if ($proof.schema_version -ne "1.2") { return $null }
    foreach ($key in @("session_id", "agent_id", "agent_type")) {
        if ((Get-PropertyValue $proof $key) -ne $runtime[$key]) { throw [ArgumentException]::new("started proof binding") }
    }
    if ($proof.state -eq "attested") { return $null }
    if ($proof.state -ne "started") { throw [ArgumentException]::new("started proof state") }
    $lastMessage = Get-PropertyValue $Payload "last_assistant_message"
    $transcriptPath = Get-PropertyValue $Payload "agent_transcript_path"
    if ($lastMessage -isnot [string] -or $transcriptPath -isnot [string] -or [string]::IsNullOrWhiteSpace($transcriptPath)) {
        throw [ArgumentException]::new("subagent stop evidence")
    }
    $matchingReceipts = @()
    foreach ($match in [regex]::Matches($lastMessage, '(?m)^xiaoh-delegation-receipt:\s*([0-9a-f]{64})\s*$')) {
        if ((Get-Sha256Hex ($utf8.GetBytes($match.Groups[1].Value))) -eq $proof.receipt_hash) {
            $matchingReceipts += $match.Groups[1].Value
        }
    }
    if ($matchingReceipts.Count -ne 1) {
        if ((Get-PropertyValue $Payload "stop_hook_active") -ne $true) {
            return [ordered]@{
                decision = "block"
                reason = "Your final response is missing the exact xiaoh-delegation-receipt line supplied by SubagentStart."
            }
        }
        return @{ systemMessage = "小H正式委派回执验证失败；本次运行不得作为专业 Agent 完成证据。" }
    }
    $properties = [ordered]@{}
    foreach ($property in $proof.PSObject.Properties) { $properties[$property.Name] = $property.Value }
    $hookPath = [IO.Path]::GetFullPath((Join-Path $CodexHome "hooks\block_reserved_root_agent.ps1"))
    $properties.state = "attested"
    $properties.attested_at = [DateTimeOffset]::UtcNow.ToString("o")
    $properties.stop_turn_id = $runtime.turn_id
    $properties.agent_transcript_path = [IO.Path]::GetFullPath($transcriptPath)
    $properties.last_message_hash = Get-Sha256Hex ($utf8.GetBytes($lastMessage))
    $properties.hook_path = $hookPath
    $properties.hook_hash = Get-Sha256Hex ([IO.File]::ReadAllBytes($hookPath))
    $temporary = Join-Path ([IO.Path]::GetDirectoryName($proofPath)) (".proof-" + [Guid]::NewGuid().ToString("N"))
    try {
        [IO.File]::WriteAllText($temporary, (($properties | ConvertTo-Json -Depth 10 -Compress) + "`n"), $utf8)
        Move-Item -LiteralPath $temporary -Destination $proofPath -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
    }
    return $null
}

function Get-BlockedAgentName([object]$ToolInput) {
    foreach ($key in @("task_name", "agent_type", "name", "nickname")) {
        $value = Get-PropertyValue $ToolInput $key
        if (@("xiaoh", "小h") -contains (ConvertTo-NormalizedAgentName $value)) { return [string]$value }
    }
    return $null
}

function Get-DelegationHeaders([object]$Message) {
    if ($Message -isnot [string]) { return $null }
    $patterns = [ordered]@{
        task_id = '(?m)^task_id:\s*(\S+)\s*$'
        task_context = '(?m)^task_context:\s*(.+?)\s*$'
        context_hash = '(?mi)^context_hash:\s*([0-9a-f]{64})\s*$'
        delegated_agent = '(?m)^delegated_agent:\s*([A-Za-z0-9_-]+)\s*$'
    }
    $headers = [ordered]@{}
    foreach ($entry in $patterns.GetEnumerator()) {
        $matches = [regex]::Matches($Message, $entry.Value)
        if ($matches.Count -ne 1) { return $null }
        $headers[$entry.Key] = $matches[0].Groups[1].Value.Trim()
    }
    return [pscustomobject]$headers
}

function Test-Delegation([object]$Payload, [string]$CodexHome, [switch]$SkipValidator, [switch]$SkipProof) {
    $toolInput = Get-PropertyValue $Payload "tool_input"
    if ($null -eq $toolInput) { return New-Denial "拒绝 Agent 调用：Hook 未收到有效的 tool_input，无法验证委派权限。" }
    $blocked = Get-BlockedAgentName $toolInput
    if ($null -ne $blocked) {
        return New-Denial "拒绝创建子 Agent '$blocked'：xiaoh/小H 是当前根线程的保留身份，只能由根线程承担，不能注册或创建同名子 Agent。"
    }
    $headers = Get-DelegationHeaders (Get-PropertyValue $toolInput "message")
    if ($null -eq $headers) { return New-Denial "拒绝 Agent 调用：委派简报缺少 task_id、task_context、context_hash 或 delegated_agent。" }
    $declared = Get-PropertyValue $toolInput "agent_type"
    if ($declared -isnot [string] -or [string]::IsNullOrWhiteSpace($declared)) {
        return New-Denial "拒绝正式 Agent 委派：当前工具调用未提供可验证的 agent_type；task_name 或消息中的 delegated_agent 不能证明已加载注册角色配置。"
    }
    if (-not [IO.Path]::IsPathRooted($headers.task_context) -or -not (Test-Path -LiteralPath $headers.task_context -PathType Leaf)) {
        return New-Denial "拒绝 Agent 调用：task_context 不是存在的绝对文件路径。"
    }
    $contextBytes = [IO.File]::ReadAllBytes($headers.task_context)
    $actualHash = Get-Sha256Hex $contextBytes
    if ($actualHash -ne $headers.context_hash.ToLowerInvariant()) { return New-Denial "拒绝 Agent 调用：context_hash 与 task_context 当前内容不一致。" }
    try { $context = [Text.Encoding]::UTF8.GetString($contextBytes) | ConvertFrom-Json } catch {
        return New-Denial "拒绝 Agent 调用：task_context 不是有效的 UTF-8 JSON。"
    }
    if ([string]$context.task_id -ne $headers.task_id) { return New-Denial "拒绝 Agent 调用：task_id 与 task_context 不一致。" }
    if (@($context.routing.delegated_agents) -notcontains $headers.delegated_agent) {
        return New-Denial ("拒绝 Agent 调用：角色 " + $headers.delegated_agent + " 未列入 task_context.routing.delegated_agents。")
    }
    $delegationNames = Get-PropertyValue $context.routing "delegation_names"
    $expectedTaskName = Get-PropertyValue $delegationNames $headers.delegated_agent
    if ($expectedTaskName -ne (Get-PropertyValue $toolInput "task_name")) {
        return New-Denial "拒绝 Agent 调用：task_name 与 task_context.routing.delegation_names 不一致。"
    }
    $agentFile = Join-Path $CodexHome ("agents\" + $headers.delegated_agent + ".toml")
    if (-not (Test-Path -LiteralPath $agentFile -PathType Leaf)) { return New-Denial ("拒绝 Agent 调用：委派角色未注册：" + $headers.delegated_agent) }
    if ((ConvertTo-NormalizedAgentName $declared) -ne (ConvertTo-NormalizedAgentName $headers.delegated_agent)) {
        return New-Denial "拒绝 Agent 调用：工具参数中的角色与 delegated_agent 不一致。"
    }
    if (-not $SkipValidator) {
        $validator = Join-Path $CodexHome "agent-system\validate.py"
        if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) { return New-Denial "拒绝 Agent 调用：缺少 task_context 校验器。" }
        $py = Get-Command py -ErrorAction SilentlyContinue
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($py) { & $py.Source -3 $validator --task-context $headers.task_context *> $null }
        elseif ($python) { & $python.Source $validator --task-context $headers.task_context *> $null }
        else { return New-Denial "拒绝 Agent 调用：未找到 Python，无法执行 task_context 门禁校验。" }
        if ($LASTEXITCODE -ne 0) { return New-Denial "拒绝 Agent 调用：task_context 门禁校验失败。" }
    }
    if (-not $SkipProof) {
        try { [void](Write-DelegationProof $Payload $toolInput $headers $CodexHome) }
        catch [ArgumentException] {
            return New-Denial ("拒绝 Agent 调用：Hook 缺少运行时绑定字段 " + $_.Exception.Message + "，无法生成委派证明。")
        }
        catch { return New-Denial "拒绝 Agent 调用：无法原子生成当前任务的委派证明。" }
    }
    return $null
}

if ($SelfTest) {
    $reserved = Test-Delegation ([pscustomobject]@{ tool_input = [pscustomobject]@{ task_name = "xiao_h" } }) $HOME -SkipValidator
    $missing = Test-Delegation ([pscustomobject]@{ tool_input = [pscustomobject]@{ task_name = "review"; message = "missing" } }) $HOME -SkipValidator
    $completeHeaders = "task_id: task-1`ntask_context: C:\missing.json`ncontext_hash: 0000000000000000000000000000000000000000000000000000000000000000`ndelegated_agent: reviewer`n"
    $missingType = Test-Delegation ([pscustomobject]@{ tool_input = [pscustomobject]@{ task_name = "review"; message = $completeHeaders } }) $HOME -SkipValidator
    $duplicate = Test-Delegation ([pscustomobject]@{ tool_input = [pscustomobject]@{ task_name = "review"; agent_type = "reviewer"; message = ($completeHeaders + "task_id: task-1`n") } }) $HOME -SkipValidator
    if ($null -eq $reserved -or $null -eq $missing -or $null -eq $missingType -or $null -eq $duplicate) { throw "agent delegation hook self-test failed" }
    $temporaryHome = Join-Path ([IO.Path]::GetTempPath()) ("xiaoh-hook-" + [Guid]::NewGuid().ToString("N"))
    try {
        [IO.Directory]::CreateDirectory((Join-Path $temporaryHome "agents")) | Out-Null
        [IO.Directory]::CreateDirectory((Join-Path $temporaryHome "hooks")) | Out-Null
        [IO.File]::WriteAllText((Join-Path $temporaryHome "agents\reviewer.toml"), 'name = "reviewer"')
        Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $temporaryHome "hooks\block_reserved_root_agent.ps1")
        $contextPath = Join-Path $temporaryHome "context.json"
        [IO.File]::WriteAllText($contextPath, '{"task_id":"task-1","routing":{"delegated_agents":["reviewer"],"delegation_names":{"reviewer":"review"}}}')
        $digest = Get-Sha256Hex ([IO.File]::ReadAllBytes($contextPath))
        $message = "task_id: task-1`ntask_context: $contextPath`ncontext_hash: $digest`ndelegated_agent: reviewer`n"
        $valid = [pscustomobject]@{
            session_id = "parent-1"; turn_id = "turn-1"; tool_use_id = "tool-1"
            tool_input = [pscustomobject]@{ task_name = "review"; agent_type = "reviewer"; message = $message }
        }
        if ($null -ne (Test-Delegation $valid $temporaryHome -SkipValidator)) { throw "valid delegation self-test failed" }
        $proofDirectory = Join-Path $temporaryHome ("agent-system\delegation-proofs\" + $digest)
        if (@(Get-ChildItem -LiteralPath $proofDirectory -Filter "*.json").Count -ne 1) { throw "delegation proof self-test failed" }
        $missingRuntime = [pscustomobject]@{ tool_input = $valid.tool_input }
        if ($null -eq (Test-Delegation $missingRuntime $temporaryHome -SkipValidator)) { throw "runtime binding self-test failed" }
        $previousThread = $env:CODEX_THREAD_ID
        $env:CODEX_THREAD_ID = "parent-2"
        try {
            $pending = Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator
            if (-not (Test-Path -LiteralPath $pending -PathType Leaf)) { throw "delegation intent self-test failed" }
            try {
                [void](Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator)
                throw "exclusive delegation-intent self-test failed"
            }
            catch [IO.IOException] {}
            $crossRole = [pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-2"
                agent_id = "agent-other"; agent_type = "other-role"
            }
            if ($null -ne (Read-SubagentStart $crossRole $temporaryHome)) { throw "cross-role intent denial self-test failed" }
            $crossSession = [pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "other-parent"; turn_id = "turn-2"
                agent_id = "agent-2"; agent_type = "reviewer"
            }
            if ($null -ne (Read-SubagentStart $crossSession $temporaryHome)) { throw "cross-session intent denial self-test failed" }
            $subagent = [pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-2"
                agent_id = "agent-2"; agent_type = "reviewer"
            }
            $subagentProof = Read-SubagentStart $subagent $temporaryHome
            if ($null -eq $subagentProof) { throw "subagent-start proof self-test failed" }
            $proof = [IO.File]::ReadAllText($subagentProof.Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $receiptMatch = [regex]::Match($subagentProof.AdditionalContext, '(?m)^xiaoh-delegation-receipt:\s*([0-9a-f]{64})\s*$')
            if ($proof.source -ne "subagent-start-stop" -or $proof.state -ne "started" -or $proof.agent_id -ne "agent-2" -or -not $receiptMatch.Success) { throw "subagent-start binding self-test failed" }
            $missingReceipt = Test-SubagentStop ([pscustomobject]@{
                hook_event_name = "SubagentStop"; session_id = "parent-2"; turn_id = "turn-3"
                agent_id = "agent-2"; agent_type = "reviewer"; agent_transcript_path = (Join-Path $temporaryHome "agent-2.jsonl")
                last_assistant_message = "review complete"; stop_hook_active = $false
            }) $temporaryHome
            if ($missingReceipt.decision -ne "block") { throw "missing delegation receipt self-test failed" }
            $validStop = Test-SubagentStop ([pscustomobject]@{
                hook_event_name = "SubagentStop"; session_id = "parent-2"; turn_id = "turn-4"
                agent_id = "agent-2"; agent_type = "reviewer"; agent_transcript_path = (Join-Path $temporaryHome "agent-2.jsonl")
                last_assistant_message = ("review complete`nxiaoh-delegation-receipt: " + $receiptMatch.Groups[1].Value); stop_hook_active = $true
            }) $temporaryHome
            if ($null -ne $validStop) { throw "delegation receipt attestation self-test failed" }
            $proof = [IO.File]::ReadAllText($subagentProof.Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
            if ($proof.state -ne "attested" -or $proof.agent_transcript_path -ne [IO.Path]::GetFullPath((Join-Path $temporaryHome "agent-2.jsonl"))) { throw "attested proof binding self-test failed" }
            $replay = [pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-3"
                agent_id = "agent-3"; agent_type = "reviewer"
            }
            if ($null -ne (Read-SubagentStart $replay $temporaryHome)) { throw "delegation-intent replay denial self-test failed" }
            $corrupt = Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator
            [IO.File]::WriteAllText($corrupt, "{", [Text.UTF8Encoding]::new($false))
            $proofCount = @(Get-ChildItem -LiteralPath $proofDirectory -Filter "*.json").Count
            $failedStart = Invoke-SubagentStart ([pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-6"
                agent_id = "agent-4"; agent_type = "reviewer"
            }) $temporaryHome
            if (
                $failedStart.hookSpecificOutput.additionalContext -ne (Get-UnauthorizedSubagentContext) -or
                [string]::IsNullOrWhiteSpace([string]$failedStart.systemMessage) -or
                @(Get-ChildItem -LiteralPath $proofDirectory -Filter "*.json").Count -ne $proofCount
            ) { throw "corrupt delegation-intent fail-closed self-test failed" }
            $corruptClaim = [IO.Path]::ChangeExtension($corrupt, (Get-Sha256Hex ([Text.Encoding]::UTF8.GetBytes("agent-4"))) + ".claimed")
            $corruptClaimBytes = [IO.File]::ReadAllBytes($corruptClaim)
            $duplicateClaim = Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator
            $duplicateClaimResult = Invoke-SubagentStart ([pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-7"
                agent_id = "agent-4"; agent_type = "reviewer"
            }) $temporaryHome
            if (
                $duplicateClaimResult.hookSpecificOutput.additionalContext -ne (Get-UnauthorizedSubagentContext) -or
                (Get-Sha256Hex ([IO.File]::ReadAllBytes($corruptClaim))) -ne (Get-Sha256Hex $corruptClaimBytes) -or
                -not (Test-Path -LiteralPath $duplicateClaim -PathType Leaf)
            ) { throw "exclusive claimed evidence self-test failed" }
            Remove-Item -LiteralPath $duplicateClaim -Force
            $missingField = Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator
            $incomplete = [IO.File]::ReadAllText($missingField, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $incomplete.PSObject.Properties.Remove("task_id")
            [IO.File]::WriteAllText($missingField, ($incomplete | ConvertTo-Json -Depth 10 -Compress), [Text.UTF8Encoding]::new($false))
            $missingFieldResult = Invoke-SubagentStart ([pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-8"
                agent_id = "agent-5"; agent_type = "reviewer"
            }) $temporaryHome
            if ($missingFieldResult.hookSpecificOutput.additionalContext -ne (Get-UnauthorizedSubagentContext)) { throw "incomplete intent fail-closed self-test failed" }
            $tamperedField = Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator
            $tampered = [IO.File]::ReadAllText($tamperedField, [Text.Encoding]::UTF8) | ConvertFrom-Json
            $tampered.effective_brief.task_id = "tampered-task"
            [IO.File]::WriteAllText($tamperedField, ($tampered | ConvertTo-Json -Depth 10 -Compress), [Text.UTF8Encoding]::new($false))
            $tamperedResult = Invoke-SubagentStart ([pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-9"
                agent_id = "agent-6"; agent_type = "reviewer"
            }) $temporaryHome
            if ($tamperedResult.hookSpecificOutput.additionalContext -ne (Get-UnauthorizedSubagentContext)) { throw "tampered effective brief fail-closed self-test failed" }
            $attestedBytes = [IO.File]::ReadAllBytes($subagentProof.Path)
            $duplicateProof = Write-DelegationIntent ([pscustomobject]@{ tool_input = $valid.tool_input }) $temporaryHome -SkipValidator
            $duplicateProofResult = Invoke-SubagentStart ([pscustomobject]@{
                hook_event_name = "SubagentStart"; session_id = "parent-2"; turn_id = "turn-10"
                agent_id = "agent-2"; agent_type = "reviewer"
            }) $temporaryHome
            if (
                $duplicateProofResult.hookSpecificOutput.additionalContext -ne (Get-UnauthorizedSubagentContext) -or
                (Get-Sha256Hex ([IO.File]::ReadAllBytes($subagentProof.Path))) -ne (Get-Sha256Hex $attestedBytes) -or
                (Test-Path -LiteralPath $duplicateProof -PathType Leaf)
            ) { throw "exclusive attested proof self-test failed" }
            $nonObjectResult = Invoke-SubagentStart ([object[]]@()) $temporaryHome
            if ($nonObjectResult.hookSpecificOutput.additionalContext -ne (Get-UnauthorizedSubagentContext)) { throw "non-object SubagentStart fail-closed self-test failed" }
        }
        finally { $env:CODEX_THREAD_ID = $previousThread }
    }
    finally { if (Test-Path -LiteralPath $temporaryHome) { Remove-Item -LiteralPath $temporaryHome -Recurse -Force } }
    Write-Host "agent delegation hook self-test passed"
    exit 0
}

$raw = [Console]::In.ReadToEnd()
try { $payload = $raw | ConvertFrom-Json } catch {
    if ($Prepare) { Write-Error "委派意图准备失败：Hook 输入不是有效 JSON。"; exit 1 }
    if ($SubagentStart) { New-SubagentStartResponse (Get-UnauthorizedSubagentContext) "小H委派Hook输入不是有效 JSON。" | ConvertTo-Json -Depth 5 -Compress; exit 0 }
    if ($SubagentStop) { @{ systemMessage = "小H委派Hook输入不是有效 JSON。" } | ConvertTo-Json -Compress; exit 0 }
    New-Denial "拒绝 Agent 调用：Hook 输入不是有效 JSON。" | ConvertTo-Json -Depth 5 -Compress
    exit 0
}
$codexHome = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) { Join-Path $HOME ".codex" } else { $env:CODEX_HOME }
$result = if ($Prepare) {
    try { Write-DelegationIntent $payload $codexHome }
    catch { Write-Error ("委派意图准备失败：" + $_.Exception.Message); exit 1 }
}
elseif ($SubagentStart) {
    Invoke-SubagentStart $payload $codexHome
}
elseif ($SubagentStop) {
    try {
        $stopped = Test-SubagentStop $payload $codexHome
        if ($null -eq $stopped) { [pscustomobject]@{} } else { $stopped }
    }
    catch { @{ systemMessage = "小H委派回执验证失败：$($_.Exception.Message)" } }
}
else {
    try { Test-Delegation $payload $codexHome }
    catch { New-Denial ("拒绝 Agent 调用：委派门禁内部校验异常（" + $_.Exception.GetType().Name + "）。") }
}
if ($null -ne $result) { $result | ConvertTo-Json -Depth 5 -Compress }
