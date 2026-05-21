param(
    [ValidateSet("toggle", "start", "stop", "restart", "status", "monitor", "supervise", "internal-start", "internal-stop", "internal-restart", "internal-status")]
    [string]$Action = "start",
    [switch]$NoBrowser,
    [string]$SessionId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$preferredPythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$launcherPythonOverride = $env:VIBELUTION_PYTHON_EXE
$requirementsPath = Join-Path $projectDir "requirements.txt"
$webDir = Join-Path $projectDir "web"
$webDistDir = Join-Path $webDir "dist"
$webDistIndex = Join-Path $webDistDir "index.html"
$runtimeDir = Join-Path $projectDir ".runtime"
$launcherDir = Join-Path $runtimeDir "launcher"
$runtimeManagerStatePath = Join-Path $runtimeDir "runtime-manager\state.json"
$launcherControlLogPath = Join-Path $launcherDir "launcher-control.log"
$runtimeSceneRoot = Join-Path $projectDir "logs\runtime_scenes"
$browserProfileDir = Join-Path $launcherDir "edge-app-profile"
$statePath = Join-Path $launcherDir "state.json"
$pythonDepsStampPath = Join-Path $launcherDir "python-deps.stamp"
$frontendDepsStampPath = Join-Path $launcherDir "frontend-deps.stamp"
$bindHost = "127.0.0.1"
$port = 8000
if ($env:VIBELUTION_PORT) {
    $parsedPort = 0
    if ([int]::TryParse($env:VIBELUTION_PORT, [ref]$parsedPort) -and $parsedPort -gt 0 -and $parsedPort -lt 65536) {
        $port = $parsedPort
    }
}
$url = "http://$bindHost`:$port"
$healthUrl = "$url/api/health"
$mode = "single_service_bundled_edge_app"
$mutexName = "Global\Vibelution.Workbench.Launcher"
$selfProcessId = $PID
$sceneSchemaVersion = 2
$script:currentRuntimeSceneId = $null
$script:currentRuntimeSceneDir = $null
$script:sceneEventSequence = @{}

function Set-LauncherEndpoint {
    param(
        [int]$ResolvedPort,
        [string]$ResolvedUrl = ""
    )

    if ($ResolvedPort -gt 0 -and $ResolvedPort -lt 65536) {
        $script:port = $ResolvedPort
    }

    $normalizedUrl = [string]::Empty
    if ($ResolvedUrl) {
        $normalizedUrl = ([string]$ResolvedUrl).Trim().TrimEnd("/")
    }
    if (-not $normalizedUrl) {
        $normalizedUrl = "http://$bindHost`:$script:port"
    }

    $script:url = $normalizedUrl
    $script:healthUrl = "$normalizedUrl/api/health"
}

function Sync-LauncherEndpointFromState {
    $state = Get-State
    if (-not $state) {
        return
    }

    $resolvedPort = $script:port
    $statePort = 0
    $rawPort = [string]$state.port
    if ($rawPort -and [int]::TryParse($rawPort, [ref]$statePort) -and $statePort -gt 0 -and $statePort -lt 65536) {
        $resolvedPort = $statePort
    }

    $resolvedUrl = if ($state.url) { [string]$state.url } else { "" }
    Set-LauncherEndpoint -ResolvedPort $resolvedPort -ResolvedUrl $resolvedUrl
}

function Write-Note {
    param([string]$Message)
    Write-Host "[Vibelution] $Message"
}

function Get-ObjectPropertyValue {
    param(
        $Object,
        [string]$Name,
        $Default = $null
    )

    if ($null -eq $Object) {
        return $Default
    }

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $Default
    }
    return $property.Value
}

function Write-LauncherControlLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )

    try {
        Ensure-Directories
        $payload = @{
            ts = (Get-Date).ToUniversalTime().ToString("o")
            level = $Level
            event = $Event
            message = $Message
            fields = if ($Fields) { $Fields } else { @{} }
        }
        $line = $payload | ConvertTo-Json -Depth 8 -Compress
        Add-Content -Path $launcherControlLogPath -Value $line -Encoding utf8

        if ($script:currentRuntimeSceneDir) {
            $relativePath = (Get-RuntimeSceneRelativePaths).LauncherControl
            $targetPath = Get-CurrentRuntimeSceneFilePath $relativePath
            $targetDir = Split-Path -Parent $targetPath
            if (-not (Test-Path $targetDir)) {
                New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            }
            Add-Content -Path $targetPath -Value $line -Encoding utf8
        }
    } catch {
    }
}

function Write-LauncherMonitorEvent {
    param(
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{}
    )

    Write-LauncherControlLog -Event $EventCode -Message $Message -Level $Level -Fields $Fields
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "desktop_monitor" `
            -EventCode $EventCode `
            -Message $Message `
            -Level $Level `
            -Outcome $Outcome `
            -Fields $Fields `
            -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).LauncherControl -TailLines 80)
    }
}

function Invoke-RuntimeManagerClient {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Mode,
        [string]$CommandType = "",
        [string]$Reason = "",
        [switch]$ForwardNoBrowser
    )

    $pythonRuntime = Resolve-PythonRuntime
    $pythonArgs = @()
    if ($pythonRuntime.PrefixArgs) {
        $pythonArgs += $pythonRuntime.PrefixArgs
    }

    if ($Mode -eq "status") {
        $pythonArgs += @("-m", "core.runtime_manager.cli", "status")
        & $pythonRuntime.FilePath @pythonArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Runtime manager status failed with exit code $LASTEXITCODE."
        }
        return
    }

    if (-not $CommandType) {
        throw "Runtime manager command mode requires -CommandType."
    }

    $timeoutSeconds = switch ($CommandType) {
        "open_workbench" { 90 }
        "close_workbench" { 60 }
        "restart_workbench" { 120 }
        default { 45 }
    }

    $pythonArgs += @("-m", "core.runtime_manager.cli", "command", $CommandType, "--requested-by", "launcher_ps", "--wait", "--timeout", "$timeoutSeconds")
    if ($Reason) {
        $pythonArgs += @("--reason", $Reason)
    }
    if ($ForwardNoBrowser) {
        $pythonArgs += "--no-browser"
    }

    & $pythonRuntime.FilePath @pythonArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime manager command '$CommandType' failed with exit code $LASTEXITCODE."
    }
}

function Ensure-Directories {
    foreach ($path in @($runtimeDir, $launcherDir, $browserProfileDir, $runtimeSceneRoot)) {
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        }
    }
}

function ConvertTo-PortableTimestampToken {
    param([datetime]$Value)

    return $Value.ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
}

function ConvertTo-RuntimeSceneIndexToken {
    param(
        [string]$Value,
        [string]$Default = "unknown"
    )

    $text = ([string]$Value).Trim().ToLowerInvariant()
    if (-not $text) {
        return $Default
    }
    $normalized = ($text -replace "[^a-z0-9]+", "-").Trim("-")
    if ($normalized) {
        return $normalized
    }
    return $Default
}

function Get-RuntimeSceneTriggerIndexToken {
    param([string]$Trigger)

    $normalized = ([string]$Trigger).Trim().ToLowerInvariant()
    switch ($normalized) {
        "start" { return "workbench-start" }
        "internal-start" { return "workbench-start" }
        "restart" { return "workbench-restart" }
        "internal-restart" { return "workbench-restart" }
        "open" { return "workbench-open" }
        "stop" { return "workbench-stop" }
        "shutdown" { return "workbench-shutdown" }
        default { return ConvertTo-RuntimeSceneIndexToken -Value $normalized -Default "workbench-run" }
    }
}

function Get-RuntimeSceneStatusIndexToken {
    param(
        [string]$Status,
        [string]$Result,
        [string]$StopReason
    )

    $normalizedStatus = ([string]$Status).Trim().ToLowerInvariant()
    $normalizedResult = ([string]$Result).Trim().ToLowerInvariant()
    if ($normalizedStatus -eq "stopped" -and $normalizedResult) {
        switch ($normalizedResult) {
            "explicit_stop" { return "manual-stop" }
            "explicit stop" { return "manual-stop" }
            "browser_window_closed" { return "window-closed" }
            "startup_failed" { return "startup-failed" }
            "backend_exited" { return "backend-exited" }
            default { return ConvertTo-RuntimeSceneIndexToken -Value $normalizedResult -Default "stopped" }
        }
    }
    return ConvertTo-RuntimeSceneIndexToken -Value $normalizedStatus -Default "unknown"
}

function Get-RuntimeSceneStatusDisplayLabel {
    param(
        [string]$Status,
        [string]$Result,
        [string]$StopReason
    )

    $normalizedStatus = ([string]$Status).Trim().ToLowerInvariant()
    $normalizedResult = ([string]$Result).Trim().ToLowerInvariant()
    $normalizedStopReason = ([string]$StopReason).Trim().ToLowerInvariant()
    if ($normalizedStatus -eq "stopped" -and ($normalizedResult -or $normalizedStopReason)) {
        switch ($normalizedResult) {
            "explicit_stop" { return "manual stop" }
            "explicit stop" { return "manual stop" }
            "browser_window_closed" { return "window closed" }
            "startup_failed" { return "startup failed" }
            "backend_exited" { return "backend exited" }
            default {
                if ($normalizedStopReason) {
                    return $normalizedStopReason -replace "[-_]+", " "
                }
                return $normalizedResult -replace "[-_]+", " "
            }
        }
    }
    switch ($normalizedStatus) {
        "running" { return "running" }
        "starting" { return "starting" }
        "queued" { return "queued" }
        "stopping" { return "stopping" }
        "stopped" { return "stopped" }
        "failed" { return "failed" }
        default {
            if ($normalizedStatus) {
                return $normalizedStatus -replace "[-_]+", " "
            }
            return "unknown"
        }
    }
}

function Get-RuntimeSceneTriggerDisplayLabel {
    param([string]$Trigger)

    $normalized = ([string]$Trigger).Trim().ToLowerInvariant()
    switch ($normalized) {
        "start" { return "workbench start" }
        "internal-start" { return "workbench start" }
        "restart" { return "workbench restart" }
        "internal-restart" { return "workbench restart" }
        "open" { return "workbench open" }
        "stop" { return "workbench stop" }
        "shutdown" { return "workbench shutdown" }
        default {
            if ($normalized) {
                return $normalized -replace "[-_]+", " "
            }
            return "workbench run"
        }
    }
}

function Get-RuntimeScenePackageIndex {
    param(
        [string]$SceneId,
        [datetime]$StartedAt,
        [string]$Trigger,
        [string]$Status = "running",
        [string]$Result = "",
        [string]$StopReason = "",
        [string]$EndedAt = ""
    )

    $localStarted = $StartedAt.ToLocalTime()
    $startedDate = $localStarted.ToString("yyyy-MM-dd")
    $startedTime = $localStarted.ToString("HH:mm:ss")
    $triggerToken = Get-RuntimeSceneTriggerIndexToken -Trigger $Trigger
    $statusToken = Get-RuntimeSceneStatusIndexToken -Status $Status -Result $Result -StopReason $StopReason
    $displayName = "{0} {1} · {2} · {3}" -f $startedDate, $startedTime, (Get-RuntimeSceneTriggerDisplayLabel -Trigger $Trigger), (Get-RuntimeSceneStatusDisplayLabel -Status $Status -Result $Result -StopReason $StopReason)
    $indexKey = "{0}_{1}_{2}_{3}" -f $startedDate, ($startedTime -replace ":", "-"), $triggerToken, $statusToken
    $tags = @(
        "runtime-scene",
        "workbench-lifecycle",
        $triggerToken,
        $statusToken,
        (ConvertTo-RuntimeSceneIndexToken -Value $Status -Default ""),
        (ConvertTo-RuntimeSceneIndexToken -Value $Result -Default ""),
        (ConvertTo-RuntimeSceneIndexToken -Value $Trigger -Default ""),
        "managed"
    ) | Where-Object { $_ } | Select-Object -Unique
    $durationSeconds = $null
    if ($EndedAt) {
        try {
            $endedDateTime = [datetime]$EndedAt
            $durationSeconds = [Math]::Max(0, [Math]::Round(($endedDateTime.ToUniversalTime() - $StartedAt.ToUniversalTime()).TotalSeconds, 3))
        } catch {
            $durationSeconds = $null
        }
    }

    $searchText = @(
        $displayName,
        $indexKey,
        $SceneId,
        $StartedAt.ToUniversalTime().ToString("o"),
        $localStarted.ToString("o"),
        $startedDate,
        $startedTime,
        $Trigger,
        $Status,
        $Result,
        $StopReason,
        $tags
    ) | Where-Object { $_ }

    return @{
        schema_version = 1
        package_id = $SceneId
        display_name = $displayName
        index_key = $indexKey
        sortable_timestamp = $StartedAt.ToUniversalTime().ToString("o")
        started_at = $StartedAt.ToUniversalTime().ToString("o")
        started_at_local = $localStarted.ToString("o")
        started_date = $startedDate
        started_time = $startedTime
        ended_at = $EndedAt
        duration_seconds = $durationSeconds
        search_text = ($searchText -join " ")
        tags = @($tags)
    }
}

function New-RuntimeSceneId {
    return ([guid]::NewGuid().ToString("N")).Substring(0, 12)
}

function ConvertTo-PlainHashtable {
    param($Value)

    if ($null -eq $Value) {
        return @{}
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = @{}
        foreach ($key in $Value.Keys) {
            $current = $Value[$key]
            if ($current -is [System.Collections.IDictionary] -or $current -is [pscustomobject]) {
                $result[$key] = ConvertTo-PlainHashtable $current
            } else {
                $result[$key] = $current
            }
        }
        return $result
    }

    $properties = @($Value.PSObject.Properties)
    if ($properties.Count -eq 0) {
        return @{}
    }

    $result = @{}
    foreach ($prop in $properties) {
        $current = $prop.Value
        if ($current -is [System.Collections.IDictionary] -or $current -is [pscustomobject]) {
            $result[$prop.Name] = ConvertTo-PlainHashtable $current
        } else {
            $result[$prop.Name] = $current
        }
    }
    return $result
}

function Merge-HashtableRecursively {
    param(
        [hashtable]$Base,
        [hashtable]$Changes
    )

    foreach ($key in $Changes.Keys) {
        $nextValue = $Changes[$key]
        if ($nextValue -is [System.Collections.IDictionary]) {
            $childBase = @{}
            if ($Base.ContainsKey($key) -and $Base[$key] -is [System.Collections.IDictionary]) {
                $childBase = ConvertTo-PlainHashtable $Base[$key]
            }
            $Base[$key] = Merge-HashtableRecursively -Base $childBase -Changes (ConvertTo-PlainHashtable $nextValue)
        } else {
            $Base[$key] = $nextValue
        }
    }
    return $Base
}

function Get-RuntimeSceneRelativePaths {
    return @{
        FrontendBuild = "raw/frontend.build.log"
        BackendStdout = "raw/backend.stdout.log"
        BackendStderr = "raw/backend.stderr.log"
        Supervisor = "raw/supervisor.log"
        Browser = "raw/browser.log"
        LauncherControl = "raw/launcher-control.log"
    }
}

function Set-CurrentRuntimeSceneContext {
    param(
        [string]$SceneId,
        [string]$SceneDir
    )

    $script:currentRuntimeSceneId = $SceneId
    $script:currentRuntimeSceneDir = $SceneDir
}

function Restore-RuntimeSceneContextFromState {
    $state = Get-State
    if (-not $state) {
        return $false
    }
    $sceneId = [string]$state.runtimeSceneId
    $sceneDir = [string]$state.runtimeSceneDir
    if (-not $sceneId -or -not $sceneDir) {
        return $false
    }
    Set-CurrentRuntimeSceneContext -SceneId $sceneId -SceneDir $sceneDir
    return $true
}

function Get-CurrentRuntimeSceneFilePath {
    param([string]$RelativePath)

    if (-not $script:currentRuntimeSceneDir) {
        throw "No runtime scene is active."
    }
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}

function Ensure-CurrentRuntimeSceneSubdirs {
    if (-not $script:currentRuntimeSceneDir) {
        return
    }
    foreach ($path in @(
        $script:currentRuntimeSceneDir,
        (Join-Path $script:currentRuntimeSceneDir "events"),
        (Join-Path $script:currentRuntimeSceneDir "raw"),
        (Join-Path $script:currentRuntimeSceneDir "conversations"),
        (Join-Path $script:currentRuntimeSceneDir "agent"),
        (Join-Path $script:currentRuntimeSceneDir "artifacts")
    )) {
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path -Force | Out-Null
        }
    }
}

function Save-RuntimeSceneManifest {
    param([hashtable]$Manifest)

    Ensure-CurrentRuntimeSceneSubdirs
    if ($Manifest.ContainsKey("started_at")) {
        try {
            $startedAt = [datetime]$Manifest.started_at
            $status = [string]$Manifest.status
            $result = [string]$Manifest.result
            $stopReason = [string]$Manifest.stop_reason
            $endedAt = [string]$Manifest.ended_at
            $packageIndex = Get-RuntimeScenePackageIndex `
                -SceneId ([string]$Manifest.runtime_scene_id) `
                -StartedAt $startedAt `
                -Trigger ([string]$Manifest.trigger) `
                -Status $status `
                -Result $result `
                -StopReason $stopReason `
                -EndedAt $endedAt
            $package = @{}
            if ($Manifest.ContainsKey("package") -and $Manifest.package -is [System.Collections.IDictionary]) {
                $package = ConvertTo-PlainHashtable $Manifest.package
            }
            $package.index_schema_version = $packageIndex.schema_version
            $package.package_id = $packageIndex.package_id
            $package.display_name = $packageIndex.display_name
            $package.index_key = $packageIndex.index_key
            $package.sortable_timestamp = $packageIndex.sortable_timestamp
            $package.started_at = $packageIndex.started_at
            $package.started_at_local = $packageIndex.started_at_local
            $package.started_date = $packageIndex.started_date
            $package.started_time = $packageIndex.started_time
            $package.ended_at = $packageIndex.ended_at
            $package.duration_seconds = $packageIndex.duration_seconds
            $package.search_text = $packageIndex.search_text
            $package.tags = $packageIndex.tags
            $Manifest.package = $package
        } catch {
        }
    }
    $manifestPath = Get-CurrentRuntimeSceneFilePath "manifest.json"
    $Manifest | ConvertTo-Json -Depth 8 | Set-Content -Path $manifestPath -Encoding utf8
}

function Get-RuntimeSceneManifest {
    if (-not $script:currentRuntimeSceneDir) {
        return @{}
    }

    $manifestPath = Get-CurrentRuntimeSceneFilePath "manifest.json"
    if (-not (Test-Path $manifestPath)) {
        return @{}
    }

    try {
        return ConvertTo-PlainHashtable (Get-Content $manifestPath -Raw | ConvertFrom-Json)
    } catch {
        return @{}
    }
}

function Update-RuntimeSceneManifest {
    param([hashtable]$Changes)

    if (-not $script:currentRuntimeSceneDir) {
        return
    }
    $manifest = Get-RuntimeSceneManifest
    if (-not ($manifest -is [System.Collections.IDictionary])) {
        $manifest = @{}
    }
    $merged = Merge-HashtableRecursively -Base (ConvertTo-PlainHashtable $manifest) -Changes (ConvertTo-PlainHashtable $Changes)
    Save-RuntimeSceneManifest -Manifest $merged
}

function Append-RuntimeSceneRawLog {
    param(
        [string]$RelativePath,
        [string]$Message
    )

    if (-not $script:currentRuntimeSceneDir) {
        return
    }

    Ensure-CurrentRuntimeSceneSubdirs
    $targetPath = Get-CurrentRuntimeSceneFilePath $RelativePath
    $targetDir = Split-Path -Parent $targetPath
    if (-not (Test-Path $targetDir)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }
    Add-Content -Path $targetPath -Value "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss.fff'))] $Message" -Encoding utf8
}

function New-RuntimeSceneRawRef {
    param(
        [string]$RelativePath,
        [int]$TailLines = 40
    )

    return @{
        path = $RelativePath
        tail_lines = $TailLines
    }
}

function Test-RuntimeSceneLifecycleEvent {
    param([hashtable]$Payload)

    $phase = ([string]$Payload.phase).Trim().ToLowerInvariant()
    $eventCode = ([string]$Payload.event_code).Trim()
    $component = ([string]$Payload.component).Trim().ToLowerInvariant()
    if ($eventCode.StartsWith("runtime.scene.")) {
        return $true
    }
    if (@("session", "startup", "shutdown", "build", "health", "supervision") -contains $phase) {
        return $true
    }
    return (@("launcher", "supervisor") -contains $component) -and (@("session", "shutdown") -contains $phase)
}

function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{},
        [object[]]$RawRefs = @()
    )

    if (-not $script:currentRuntimeSceneDir -or -not $script:currentRuntimeSceneId) {
        return
    }

    Ensure-CurrentRuntimeSceneSubdirs
    $sequenceKey = ([string]$Component).ToLowerInvariant()
    if (-not $script:sceneEventSequence.ContainsKey($sequenceKey)) {
        $script:sceneEventSequence[$sequenceKey] = 0
    }
    $script:sceneEventSequence[$sequenceKey] = [int]$script:sceneEventSequence[$sequenceKey] + 1

    $payload = @{
        schema_version = $sceneSchemaVersion
        runtime_scene_id = $script:currentRuntimeSceneId
        ts = (Get-Date).ToUniversalTime().ToString("o")
        seq = [int]$script:sceneEventSequence[$sequenceKey]
        component = $Component
        phase = $Phase
        event_code = $EventCode
        level = $Level
        outcome = $Outcome
        message = $Message
        fields = if ($Fields) { $Fields } else { @{} }
        raw_refs = if ($RawRefs) { @($RawRefs) } else { @() }
    }

    $eventsPath = Get-CurrentRuntimeSceneFilePath ("events/{0}.jsonl" -f $sequenceKey)
    $payloadJson = $payload | ConvertTo-Json -Depth 8 -Compress
    $payloadJson | Add-Content -Path $eventsPath -Encoding utf8
    $payloadJson | Add-Content -Path (Get-CurrentRuntimeSceneFilePath "timeline.jsonl") -Encoding utf8
    if (Test-RuntimeSceneLifecycleEvent -Payload $payload) {
        $payloadJson | Add-Content -Path (Get-CurrentRuntimeSceneFilePath "lifecycle.jsonl") -Encoding utf8
    }
}

function Initialize-RuntimeScene {
    param(
        [string]$Trigger,
        [bool]$BrowserManaged
    )

    Ensure-Directories
    $startedAt = (Get-Date).ToUniversalTime()
    $sceneId = New-RuntimeSceneId
    $directoryName = "{0}__{1}" -f (ConvertTo-PortableTimestampToken $startedAt), $sceneId
    $sceneDir = Join-Path $runtimeSceneRoot $directoryName
    Set-CurrentRuntimeSceneContext -SceneId $sceneId -SceneDir $sceneDir
    Ensure-CurrentRuntimeSceneSubdirs
    $packageIndex = Get-RuntimeScenePackageIndex -SceneId $sceneId -StartedAt $startedAt -Trigger $Trigger -Status "running"

    $rawPaths = Get-RuntimeSceneRelativePaths
    foreach ($relativePath in $rawPaths.Values) {
        $targetPath = Get-CurrentRuntimeSceneFilePath $relativePath
        $targetDir = Split-Path -Parent $targetPath
        if (-not (Test-Path $targetDir)) {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        }
        Set-Content -Path $targetPath -Value "" -Encoding utf8
    }

    Save-RuntimeSceneManifest -Manifest @{
        schema_version = $sceneSchemaVersion
        runtime_scene_id = $sceneId
        title = "Managed workbench run $sceneId"
        package = @{
            schema_version = 2
            index_schema_version = $packageIndex.schema_version
            package_id = $packageIndex.package_id
            display_name = $packageIndex.display_name
            index_key = $packageIndex.index_key
            sortable_timestamp = $packageIndex.sortable_timestamp
            started_at = $packageIndex.started_at
            started_at_local = $packageIndex.started_at_local
            started_date = $packageIndex.started_date
            started_time = $packageIndex.started_time
            ended_at = $packageIndex.ended_at
            duration_seconds = $packageIndex.duration_seconds
            search_text = $packageIndex.search_text
            tags = $packageIndex.tags
            timeline_path = "timeline.jsonl"
            lifecycle_path = "lifecycle.jsonl"
            raw_dir = "raw"
            conversations_dir = "conversations"
            agent_dir = "agent"
            artifacts_dir = "artifacts"
            updated_at = $startedAt.ToString("o")
        }
        started_at = $startedAt.ToString("o")
        ended_at = ""
        status = "running"
        result = ""
        stop_reason = ""
        trigger = $Trigger
        session_mode = "managed"
        project_root = $projectDir
        host = $bindHost
        port = $port
        url = $url
        frontend = @{
            build_status = "pending"
            build_reason = ""
            log_path = $rawPaths.FrontendBuild
        }
        backend = @{
            pid = 0
            health_status = "pending"
            stdout_path = $rawPaths.BackendStdout
            stderr_path = $rawPaths.BackendStderr
        }
        browser = @{
            managed = $BrowserManaged
            status = if ($BrowserManaged) { "pending" } else { "disabled" }
            log_path = $rawPaths.Browser
            executable = ""
            launch_pid = 0
            window_pid = 0
        }
        launcher = @{
            control_log_path = $rawPaths.LauncherControl
            visible_monitor = "not_started"
        }
        supervisor = @{
            pid = 0
            status = if ($BrowserManaged) { "pending" } else { "disabled" }
            log_path = $rawPaths.Supervisor
        }
    }

    Write-RuntimeSceneEvent `
        -Component "launcher" `
        -Phase "session" `
        -EventCode "runtime.scene.created" `
        -Message "Created runtime scene bundle." `
        -Outcome "started" `
        -Fields @{
            directory_name = $directoryName
            browser_managed = $BrowserManaged
            trigger = $Trigger
        }
}

function Get-RuntimeSceneFinalState {
    param([string]$Reason)

    $normalized = ([string]$Reason).Trim().ToLowerInvariant()
    if ($normalized -match "startup failure") {
        return @{ status = "failed"; result = "startup_failed" }
    }
    if ($normalized -match "backend exited") {
        return @{ status = "failed"; result = "backend_exited" }
    }
    if ($normalized -match "app window closed") {
        return @{ status = "stopped"; result = "browser_window_closed" }
    }
    return @{ status = "stopped"; result = ($normalized -replace "[^a-z0-9]+", "_").Trim('_') }
}

function Get-StringHash {
    param([string]$Value)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-FileFingerprint {
    param([string[]]$Paths)

    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($path in @($Paths | Where-Object { $_ })) {
        if (-not (Test-Path $path)) {
            [void]$parts.Add("$path|missing")
            continue
        }

        $item = Get-Item $path
        if ($item -is [System.IO.DirectoryInfo]) {
            throw "Get-FileFingerprint only accepts files. Received directory: $path"
        }

        $hash = (Get-FileHash -Path $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$parts.Add("$($item.FullName)|$($item.Length)|$hash")
    }

    return Get-StringHash -Value ($parts -join "`n")
}

function Get-StoredStampValue {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }

    return (Get-Content $Path -Raw).Trim()
}

function Set-StoredStampValue {
    param(
        [string]$Path,
        [string]$Value
    )

    Ensure-Directories
    Set-Content -Path $Path -Value $Value -Encoding ascii
}

function Get-RuntimeManagerState {
    if (-not (Test-Path $runtimeManagerStatePath)) {
        return $null
    }

    try {
        return Get-Content $runtimeManagerStatePath -Raw | ConvertFrom-Json
    } catch {
        Write-LauncherControlLog `
            -Event "launcher.monitor.runtime_manager_state_unreadable" `
            -Message "Runtime manager state file is unreadable." `
            -Level "warning" `
            -Fields @{ path = $runtimeManagerStatePath; error = $_.Exception.Message }
        return $null
    }
}

function Get-RuntimeManagerWorkbench {
    $managerState = Get-RuntimeManagerState
    if (-not $managerState) {
        return $null
    }

    return Get-ObjectPropertyValue -Object $managerState -Name "workbench" -Default $null
}

function Get-RuntimeManagerWorkbenchReason {
    param(
        $Workbench,
        [string]$Fallback = "workbench lifecycle closed"
    )

    $reason = [string](Get-ObjectPropertyValue -Object $Workbench -Name "lastReason" -Default "")
    if ($reason) {
        return $reason
    }
    return $Fallback
}

function Get-RuntimeManagerWorkbenchSource {
    param(
        $Workbench,
        [string]$Fallback = "runtime_manager"
    )

    $source = [string](Get-ObjectPropertyValue -Object $Workbench -Name "lastSource" -Default "")
    if ($source) {
        return $source
    }
    return $Fallback
}

function Wait-ForRuntimeManagerWorkbenchOpen {
    param([int]$TimeoutSeconds = 45)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $workbench = Get-RuntimeManagerWorkbench
        if ($workbench) {
            $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
            $observedState = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
            $phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
            if ($desiredState -eq "open" -and $observedState -eq "open" -and $phase -eq "steady") {
                return $true
            }
            if ($phase -eq "failed") {
                return $false
            }
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-LatestInputTimeUtc {
    param(
        [string[]]$Paths,
        [string[]]$Extensions = @()
    )

    $normalizedExtensions = @($Extensions | Where-Object { $_ } | ForEach-Object { $_.ToLowerInvariant() })
    $latestInput = [datetime]::MinValue

    foreach ($path in @($Paths | Where-Object { $_ })) {
        if (-not (Test-Path $path)) {
            continue
        }

        $rootItem = Get-Item $path
        $items = @()
        if ($rootItem -is [System.IO.DirectoryInfo]) {
            $items = @(Get-ChildItem $path -Recurse -File)
        } else {
            $items = @($rootItem)
        }

        foreach ($item in $items) {
            if ($normalizedExtensions.Count -gt 0 -and ($normalizedExtensions -notcontains $item.Extension.ToLowerInvariant())) {
                continue
            }
            if ($item.LastWriteTimeUtc -gt $latestInput) {
                $latestInput = $item.LastWriteTimeUtc
            }
        }
    }

    return $latestInput
}

function Get-FrontendInputTimeUtc {
    return Get-LatestInputTimeUtc -Paths @(
        (Join-Path $webDir "src"),
        (Join-Path $webDir "public"),
        (Join-Path $webDir "package.json"),
        (Join-Path $webDir "package-lock.json"),
        (Join-Path $webDir "tsconfig.json"),
        (Join-Path $webDir "tsconfig.app.json"),
        (Join-Path $webDir "tsconfig.node.json"),
        (Join-Path $webDir "vite.config.ts"),
        (Join-Path $webDir "vite.config.js")
    )
}

function Get-BackendInputTimeUtc {
    return Get-LatestInputTimeUtc `
        -Paths @(
            (Join-Path $projectDir "agent.py"),
            (Join-Path $projectDir "core"),
            (Join-Path $projectDir "scripts"),
            (Join-Path $projectDir "config"),
            $requirementsPath,
            (Join-Path $projectDir "config.toml")
        ) `
        -Extensions @(".py", ".ps1", ".psm1", ".json", ".toml", ".txt", ".html", ".css", ".js", ".ts", ".tsx")
}

function Get-WebDistTimeUtc {
    if (-not (Test-Path $webDistIndex)) {
        return [datetime]::MinValue
    }

    return (Get-Item $webDistIndex).LastWriteTimeUtc
}

function Acquire-LauncherMutex {
    if ($Action -eq "supervise" -or $Action -eq "monitor") {
        return
    }

    $script:launcherMutex = New-Object System.Threading.Mutex($false, $mutexName)
    $acquired = $script:launcherMutex.WaitOne([TimeSpan]::FromSeconds(30))
    if (-not $acquired) {
        throw "Another Vibelution launcher action is still running. Try again in a moment."
    }
}

function Release-LauncherMutex {
    if ($Action -eq "supervise" -or $Action -eq "monitor") {
        return
    }

    if ($script:launcherMutex) {
        try {
            $script:launcherMutex.ReleaseMutex() | Out-Null
        } catch {
        }
        $script:launcherMutex.Dispose()
    }
}

function Get-State {
    if (-not (Test-Path $statePath)) {
        return $null
    }

    try {
        return Get-Content $statePath -Raw | ConvertFrom-Json
    } catch {
        Write-Note "State file is unreadable. Removing stale launcher state."
        Remove-Item $statePath -Force -ErrorAction SilentlyContinue
        return $null
    }
}

function Save-State {
    param([hashtable]$State)

    Ensure-Directories
    $State | ConvertTo-Json -Depth 6 | Set-Content -Path $statePath -Encoding utf8
}

function Remove-State {
    if (Test-Path $statePath) {
        Remove-Item $statePath -Force -ErrorAction SilentlyContinue
    }
}

function Test-ProcessAlive {
    param([int]$ProcessId)

    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Stop-ProcessesById {
    param([int[]]$ProcessIds)

    foreach ($processId in @($ProcessIds | Sort-Object -Unique)) {
        if (-not $processId) {
            continue
        }
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ListeningPid {
    param([int]$Port)

    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        return [int]$listener.OwningProcess
    }
    return $null
}

function Wait-ForPortClosed {
    param([int]$Port, [int]$TimeoutSeconds = 12)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-ListeningPid $Port)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return $false
}

function Wait-ForBackendHealthy {
    param(
        [int]$ProcessId,
        [int]$TimeoutSeconds = 25
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-ProcessAlive $ProcessId)) {
            return $false
        }
        if (Test-WebHealthy) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-LogTail {
    param([string]$Path, [int]$Lines = 40)

    if (-not (Test-Path $Path)) {
        return ""
    }

    return ((Get-Content $Path -Tail $Lines) -join [Environment]::NewLine)
}

function Test-WebHealthy {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Resolve-NpmCommand {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) {
        $npm = Get-Command npm -ErrorAction SilentlyContinue
    }
    if (-not $npm) {
        throw "npm is not available on PATH."
    }
    return $npm.Source
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandPath,
        [string[]]$ArgumentList = @(),
        [string]$RedirectPath = ""
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $nativePreferenceDefined = Test-Path Variable:PSNativeCommandUseErrorActionPreference
    $previousNativePreference = $null
    if ($nativePreferenceDefined) {
        $previousNativePreference = $PSNativeCommandUseErrorActionPreference
    }

    try {
        $ErrorActionPreference = "Continue"
        if ($nativePreferenceDefined) {
            $PSNativeCommandUseErrorActionPreference = $false
        }

        if ($RedirectPath) {
            & $CommandPath @ArgumentList *>> $RedirectPath
        } else {
            & $CommandPath @ArgumentList
        }

        return $LASTEXITCODE
    } finally {
        if ($nativePreferenceDefined) {
            $PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-PythonRuntime {
    param(
        [string]$CommandPath,
        [string[]]$PrefixArgs = @()
    )

    try {
        & $CommandPath @PrefixArgs -c "import fastapi, uvicorn" *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-ProjectPythonCandidates {
    $venvCandidates = New-Object System.Collections.Generic.List[object]

    if ($launcherPythonOverride -and (Test-Path $launcherPythonOverride)) {
        [void]$venvCandidates.Add([pscustomobject]@{
            FilePath = (Resolve-Path $launcherPythonOverride).Path
            PrefixArgs = @()
            Label = "launcher virtual environment"
        })
    }

    if (Test-Path $preferredPythonExe) {
        $resolvedPreferredPythonExe = (Resolve-Path $preferredPythonExe).Path
        if (-not @($venvCandidates | Where-Object { $_.FilePath -eq $resolvedPreferredPythonExe })) {
            [void]$venvCandidates.Add([pscustomobject]@{
                FilePath = $resolvedPreferredPythonExe
                PrefixArgs = @()
                Label = "project venv"
            })
        }
    }

    return $venvCandidates.ToArray()
}

function Ensure-ProjectPythonDependencies {
    $venvCandidates = @(Get-ProjectPythonCandidates)
    if ($venvCandidates.Count -eq 0) {
        return
    }

    $requirementsFingerprint = $null
    if (Test-Path $requirementsPath) {
        $requirementsFingerprint = Get-FileFingerprint -Paths @($requirementsPath)
    }
    $storedFingerprint = Get-StoredStampValue -Path $pythonDepsStampPath
    $runtimeReady = $false

    foreach ($candidate in $venvCandidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            $runtimeReady = $true
            break
        }
    }

    if ($runtimeReady -and -not $requirementsFingerprint) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.current" `
                -Message "Backend runtime dependencies are current." `
                -Outcome "succeeded"
        }
        return
    }

    if ($runtimeReady -and $requirementsFingerprint -and $storedFingerprint -eq $requirementsFingerprint) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.current" `
                -Message "Backend runtime dependencies are current." `
                -Outcome "succeeded"
        }
        return
    }

    if ($runtimeReady -and $requirementsFingerprint -and -not $storedFingerprint) {
        Write-Note "Recording the current Python dependency fingerprint."
        Set-StoredStampValue -Path $pythonDepsStampPath -Value $requirementsFingerprint
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.stamped" `
                -Message "Recorded the current Python dependency fingerprint." `
                -Outcome "succeeded"
        }
        return
    }

    if (-not (Test-Path $requirementsPath)) {
        throw "Project virtual environment was found, but requirements.txt is missing at $requirementsPath"
    }

    $installTarget = $venvCandidates[0]
    $installExitCode = 0
    $maxInstallAttempts = 3
    $installReason = if (-not $runtimeReady) {
        "backend runtime imports are incomplete"
    } elseif (-not $storedFingerprint) {
        "dependency stamp is missing"
    } else {
        "requirements.txt changed"
    }

    for ($attempt = 1; $attempt -le $maxInstallAttempts; $attempt++) {
        Write-Note "Installing Python dependencies into $($installTarget.Label) ($installReason, attempt $attempt/$maxInstallAttempts) ..."
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.install.started" `
                -Message "Installing Python dependencies." `
                -Outcome "started" `
                -Fields @{ reason = $installReason; attempt = $attempt; max_attempts = $maxInstallAttempts }
        }
        & $installTarget.FilePath @($installTarget.PrefixArgs + @("-m", "pip", "install", "--disable-pip-version-check", "-r", $requirementsPath))
        $installExitCode = $LASTEXITCODE
        if ($installExitCode -eq 0) {
            break
        }
        if ($attempt -lt $maxInstallAttempts) {
            Write-Note "Dependency install attempt $attempt failed with exit code $installExitCode. Retrying in 2 seconds..."
            Start-Sleep -Seconds 2
        }
    }

    if ($installExitCode -ne 0) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "python_dependencies" `
                -EventCode "backend.dependencies.install.failed" `
                -Message "Installing Python dependencies failed." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ reason = $installReason; exit_code = $installExitCode }
        }
        throw "Installing Python dependencies failed with exit code $installExitCode."
    }

    foreach ($candidate in $venvCandidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            if ($requirementsFingerprint) {
                Set-StoredStampValue -Path $pythonDepsStampPath -Value $requirementsFingerprint
            }
            if ($script:currentRuntimeSceneId) {
                Write-RuntimeSceneEvent `
                    -Component "launcher" `
                    -Phase "python_dependencies" `
                    -EventCode "backend.dependencies.install.succeeded" `
                    -Message "Python dependencies are ready." `
                    -Outcome "succeeded" `
                    -Fields @{ runtime = $candidate.Label }
            }
            return
        }
    }

    $venvPaths = ($venvCandidates | ForEach-Object { $_.FilePath } | Sort-Object -Unique) -join ", "
    throw "Project virtual environment dependency install completed, but backend imports still failed. Checked: $venvPaths"
}

function Resolve-PythonRuntime {
    $venvCandidates = @(Get-ProjectPythonCandidates)

    foreach ($candidate in $venvCandidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            return $candidate
        }
    }

    if ($venvCandidates.Count -gt 0) {
        $venvPaths = ($venvCandidates | ForEach-Object { $_.FilePath } | Sort-Object -Unique) -join ", "
        throw "Project virtual environment was found but is not usable. Expected a Python runtime that can import uvicorn. Checked: $venvPaths"
    }

    $candidates = New-Object System.Collections.Generic.List[object]

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        [void]$candidates.Add([pscustomobject]@{
            FilePath = $pythonCommand.Source
            PrefixArgs = @()
            Label = "python on PATH"
        })
    }

    foreach ($candidate in $candidates) {
        if (Test-PythonRuntime -CommandPath $candidate.FilePath -PrefixArgs $candidate.PrefixArgs) {
            return $candidate
        }
    }

    throw "No usable Python runtime was found. Expected one that can import uvicorn."
}

function Resolve-EdgeExecutable {
    $pathCandidates = @()

    if ($env:ProgramFiles -and (Test-Path $env:ProgramFiles)) {
        $pathCandidates += (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe")
    }
    if (${env:ProgramFiles(x86)} -and (Test-Path ${env:ProgramFiles(x86)})) {
        $pathCandidates += (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe")
    }
    if ($env:LocalAppData -and (Test-Path $env:LocalAppData)) {
        $pathCandidates += (Join-Path $env:LocalAppData "Microsoft\Edge\Application\msedge.exe")
    }

    foreach ($candidate in $pathCandidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return (Resolve-Path $candidate).Path
        }
    }

    $edgeCommand = Get-Command msedge.exe -ErrorAction SilentlyContinue
    if ($edgeCommand) {
        return $edgeCommand.Source
    }

    $edgeProcess = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -ieq "msedge.exe" -and $_.ExecutablePath
    } | Select-Object -First 1
    if ($edgeProcess -and (Test-Path $edgeProcess.ExecutablePath)) {
        return (Resolve-Path $edgeProcess.ExecutablePath).Path
    }

    throw "Microsoft Edge was not found. Install Edge or update the launcher path."
}

function Get-WebBuildReason {
    if (-not (Test-Path $webDistIndex)) {
        return "web/dist is missing"
    }

    $latestInput = Get-FrontendInputTimeUtc
    $distTime = Get-WebDistTimeUtc
    if ($latestInput -gt $distTime) {
        return "frontend sources changed"
    }

    return $null
}

function Ensure-FrontendDependencies {
    $packageJsonPath = Join-Path $webDir "package.json"
    $packageLockPath = Join-Path $webDir "package-lock.json"
    $dependencyFiles = @($packageLockPath, $packageJsonPath) | Where-Object { Test-Path $_ }
    if ($dependencyFiles.Count -eq 0) {
        throw "Frontend dependency manifests are missing from $webDir"
    }

    $nodeModulesDir = Join-Path $webDir "node_modules"
    $tscBinPath = Join-Path $nodeModulesDir ".bin\tsc.cmd"
    $viteBinPath = Join-Path $nodeModulesDir ".bin\vite.cmd"
    $toolchainReady = (Test-Path $tscBinPath) -and (Test-Path $viteBinPath)
    $dependencyFingerprint = Get-FileFingerprint -Paths $dependencyFiles
    $storedFingerprint = Get-StoredStampValue -Path $frontendDepsStampPath
    if ((Test-Path $nodeModulesDir) -and $toolchainReady -and $storedFingerprint -eq $dependencyFingerprint) {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "dependencies" `
                -EventCode "frontend.dependencies.current" `
                -Message "Frontend dependencies are current." `
                -Outcome "succeeded"
        }
        return
    }

    if ((Test-Path $nodeModulesDir) -and $toolchainReady -and -not $storedFingerprint) {
        Write-Note "Recording the current frontend dependency fingerprint."
        Set-StoredStampValue -Path $frontendDepsStampPath -Value $dependencyFingerprint
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "dependencies" `
                -EventCode "frontend.dependencies.stamped" `
                -Message "Recorded the current frontend dependency fingerprint." `
                -Outcome "succeeded"
        }
        return
    }

    $npmCommand = Resolve-NpmCommand
    $installCommandName = if ((-not (Test-Path $nodeModulesDir)) -and (Test-Path $packageLockPath)) {
        "ci"
    } else {
        "install"
    }
    $installReason = if (-not (Test-Path $nodeModulesDir)) {
        "node_modules is missing"
    } elseif (-not $toolchainReady) {
        "frontend build tools are missing from node_modules"
    } elseif (-not $storedFingerprint) {
        "dependency stamp is missing"
    } else {
        "frontend dependency manifests changed"
    }

    Write-Note "Installing frontend dependencies ($installReason)..."
    if ($script:currentRuntimeSceneId) {
        Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).FrontendBuild -Message "Installing frontend dependencies ($installReason)."
        Write-RuntimeSceneEvent `
            -Component "frontend" `
            -Phase "dependencies" `
            -EventCode "frontend.dependencies.install.started" `
            -Message "Installing frontend dependencies." `
            -Outcome "started" `
            -Fields @{ reason = $installReason }
    }
    Push-Location $webDir
    try {
        $frontendBuildLogPath = $null
        if ($script:currentRuntimeSceneId) {
            $frontendBuildLogPath = Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).FrontendBuild
        }
        $installArgs = @($installCommandName)
        $exitCode = Invoke-NativeCommand -CommandPath $npmCommand -ArgumentList $installArgs -RedirectPath $frontendBuildLogPath
        if ($exitCode -ne 0) {
            if ($script:currentRuntimeSceneId) {
                Write-RuntimeSceneEvent `
                    -Component "frontend" `
                    -Phase "dependencies" `
                    -EventCode "frontend.dependencies.install.failed" `
                    -Message "Installing frontend dependencies failed." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields @{ reason = $installReason; exit_code = $exitCode } `
                    -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).FrontendBuild -TailLines 80)
            }
            throw "npm $installCommandName failed with exit code $exitCode."
        }
    } finally {
        Pop-Location
    }

    Set-StoredStampValue -Path $frontendDepsStampPath -Value $dependencyFingerprint
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "frontend" `
            -Phase "dependencies" `
            -EventCode "frontend.dependencies.install.succeeded" `
            -Message "Frontend dependencies installed successfully." `
            -Outcome "succeeded" `
            -Fields @{ reason = $installReason; command = $installCommandName }
    }
}

function Ensure-WebBuild {
    Ensure-FrontendDependencies

    $buildReason = Get-WebBuildReason
    if (-not $buildReason) {
        Write-Note "Frontend build is current."
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ frontend = @{ build_status = "current"; build_reason = "" } }
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "build" `
                -EventCode "frontend.build.current" `
                -Message "Frontend build is current." `
                -Outcome "succeeded"
        }
        return
    }

    $npmCommand = Resolve-NpmCommand
    Push-Location $webDir
    try {
        Write-Note "Building frontend bundle ($buildReason)..."
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ frontend = @{ build_status = "running"; build_reason = $buildReason } }
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "build" `
                -EventCode "frontend.build.started" `
                -Message "Starting frontend build." `
                -Outcome "started" `
                -Fields @{ reason = $buildReason }
            $exitCode = Invoke-NativeCommand `
                -CommandPath $npmCommand `
                -ArgumentList @("run", "build") `
                -RedirectPath (Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).FrontendBuild)
        } else {
            $exitCode = Invoke-NativeCommand -CommandPath $npmCommand -ArgumentList @("run", "build")
        }
        if ($exitCode -ne 0) {
            if ($script:currentRuntimeSceneId) {
                Update-RuntimeSceneManifest @{ frontend = @{ build_status = "failed"; build_reason = $buildReason } }
                Write-RuntimeSceneEvent `
                    -Component "frontend" `
                    -Phase "build" `
                    -EventCode "frontend.build.failed" `
                    -Message "Frontend build failed." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields @{ reason = $buildReason; exit_code = $exitCode } `
                    -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).FrontendBuild -TailLines 120)
            }
            throw "npm run build failed with exit code $exitCode."
        }
    } finally {
        Pop-Location
    }

    if (-not (Test-Path $webDistIndex)) {
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ frontend = @{ build_status = "failed"; build_reason = $buildReason } }
            Write-RuntimeSceneEvent `
                -Component "frontend" `
                -Phase "build" `
                -EventCode "frontend.build.missing_output" `
                -Message "Frontend build completed without index.html." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ reason = $buildReason }
        }
        throw "Frontend build finished without producing web/dist/index.html."
    }

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ frontend = @{ build_status = "success"; build_reason = $buildReason } }
        Write-RuntimeSceneEvent `
            -Component "frontend" `
            -Phase "build" `
            -EventCode "frontend.build.succeeded" `
            -Message "Frontend build completed successfully." `
            -Outcome "succeeded" `
            -Fields @{ reason = $buildReason; output = "web/dist/index.html" }
    }
}

function Get-ManagedBackendCandidatePids {
    $pids = New-Object System.Collections.Generic.List[int]
    $state = Get-State
    if ($state -and $state.backendPid) {
        $trackedPid = [int]$state.backendPid
        if (Test-ProcessAlive $trackedPid) {
            [void]$pids.Add($trackedPid)
        }
    }

    $listenerPid = Get-ListeningPid $port
    if ($listenerPid) {
        $listenerProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $listenerPid" -ErrorAction SilentlyContinue
        if ($listenerProcess -and $listenerProcess.CommandLine -and $listenerProcess.CommandLine -match "scripts[\\/]+web_workbench\.py") {
            [void]$pids.Add([int]$listenerPid)
        }
    }

    $scanPids = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "scripts[\\/]+web_workbench\.py" -and $_.CommandLine -match "--port\s+$port\b"
    } | ForEach-Object {
        [int]$_.ProcessId
    })

    foreach ($candidatePid in $scanPids) {
        [void]$pids.Add($candidatePid)
    }

    return @($pids | Sort-Object -Unique)
}

function Get-ManagedBrowserProcesses {
    Ensure-Directories
    $profileMarker = [regex]::Escape([System.IO.Path]::GetFullPath($browserProfileDir))

    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -ieq "msedge.exe" -and $_.CommandLine -and $_.CommandLine -match $profileMarker
    })
}

function Get-ManagedBrowserPids {
    return @(Get-ManagedBrowserProcesses | ForEach-Object { [int]$_.ProcessId } | Sort-Object -Unique)
}

function Get-ManagedBrowserWindowProcesses {
    $browserPids = @(Get-ManagedBrowserPids)
    if ($browserPids.Count -eq 0) {
        return @()
    }

    return @(Get-Process -Id $browserPids -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowHandle -ne 0
    })
}

function Get-ManagedBrowserWindowProcess {
    $windowProcesses = @(Get-ManagedBrowserWindowProcesses)
    if ($windowProcesses.Count -gt 0) {
        return $windowProcesses[0]
    }
    return $null
}

function Wait-ForBrowserWindow {
    param(
        [int]$LaunchProcessId,
        [int]$TimeoutSeconds = 18
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $windowProcess = Get-ManagedBrowserWindowProcess
        if ($windowProcess) {
            return $windowProcess
        }

        $browserPids = @(Get-ManagedBrowserPids)
        if ($browserPids.Count -eq 0 -and -not (Test-ProcessAlive $LaunchProcessId)) {
            return $null
        }

        Start-Sleep -Milliseconds 400
    }
    return $null
}

function Wait-ForBrowserStopped {
    param([int]$TimeoutSeconds = 12)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (@(Get-ManagedBrowserPids).Count -eq 0) {
            return $true
        }
        Start-Sleep -Milliseconds 300
    }
    return $false
}

function Ensure-WinApi {
    if (-not ("VibelutionLauncher.WinApi" -as [type])) {
        Add-Type @"
using System;
using System.Runtime.InteropServices;

namespace VibelutionLauncher {
    public static class WinApi {
        [DllImport("user32.dll")]
        public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

        [DllImport("user32.dll")]
        public static extern bool SetForegroundWindow(IntPtr hWnd);
    }
}
"@
    }
}

function Focus-ManagedBrowserWindow {
    $windowProcess = Get-ManagedBrowserWindowProcess
    if (-not $windowProcess) {
        return $false
    }

    Ensure-WinApi
    try {
        [VibelutionLauncher.WinApi]::ShowWindowAsync([IntPtr]$windowProcess.MainWindowHandle, 9) | Out-Null
        Start-Sleep -Milliseconds 120
        [VibelutionLauncher.WinApi]::SetForegroundWindow([IntPtr]$windowProcess.MainWindowHandle) | Out-Null
    } catch {
    }

    try {
        $wshShell = New-Object -ComObject WScript.Shell
        $wshShell.AppActivate($windowProcess.Id) | Out-Null
    } catch {
    }

    return $true
}

function Start-ManagedBackend {
    param([pscustomobject]$PythonRuntime)

    $backendStdoutLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).BackendStdout
    } else {
        Join-Path $launcherDir "web-backend.out.log"
    }
    $backendStderrLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).BackendStderr
    } else {
        Join-Path $launcherDir "web-backend.err.log"
    }

    Write-Note "Starting bundled web service at $url ..."
    Write-Note "Python runtime: $($PythonRuntime.Label) -> $($PythonRuntime.FilePath)"
    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{
            backend = @{
                pid = 0
                health_status = "starting"
                python_label = $PythonRuntime.Label
                python_command = $PythonRuntime.FilePath
            }
        }
        Write-RuntimeSceneEvent `
            -Component "backend" `
            -Phase "startup" `
            -EventCode "backend.start.requested" `
            -Message "Starting bundled backend service." `
            -Outcome "started" `
            -Fields @{ host = $bindHost; port = $port; python_label = $PythonRuntime.Label }
    }
    $proc = Start-Process `
        -FilePath $PythonRuntime.FilePath `
        -ArgumentList @($PythonRuntime.PrefixArgs + @("scripts/web_workbench.py", "--host", $bindHost, "--port", "$port", "--no-browser")) `
        -WorkingDirectory $projectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendStdoutLog `
        -RedirectStandardError $backendStderrLog `
        -PassThru

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ backend = @{ pid = $proc.Id; health_status = "starting" } }
        Write-RuntimeSceneEvent `
            -Component "backend" `
            -Phase "startup" `
            -EventCode "backend.process.started" `
            -Message "Backend process started." `
            -Outcome "started" `
            -Fields @{ pid = $proc.Id }
    }

    if (-not (Wait-ForBackendHealthy -ProcessId $proc.Id)) {
        Stop-ProcessesById @($proc.Id)
        $tail = Get-LogTail -Path $backendStderrLog
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ backend = @{ pid = $proc.Id; health_status = "failed" } }
            Write-RuntimeSceneEvent `
                -Component "backend" `
                -Phase "health" `
                -EventCode "backend.health.failed" `
                -Message "Backend failed to become healthy." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ pid = $proc.Id } `
                -RawRefs @(New-RuntimeSceneRawRef -RelativePath (Get-RuntimeSceneRelativePaths).BackendStderr -TailLines 80)
        }
        throw "Bundled web service failed to become healthy.$([Environment]::NewLine)$tail"
    }

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ backend = @{ pid = $proc.Id; health_status = "healthy" } }
        Write-RuntimeSceneEvent `
            -Component "backend" `
            -Phase "health" `
            -EventCode "backend.health.succeeded" `
            -Message "Backend passed health checks." `
            -Outcome "succeeded" `
            -Fields @{ pid = $proc.Id; url = $url }
    }

    return $proc
}

function Start-ManagedBrowser {
    param([string]$BrowserExecutable)

    $browserArgs = @(
        "--user-data-dir=$browserProfileDir",
        "--app=$url",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble"
    )

    Write-Note "Starting managed Edge app window ..."
    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ browser = @{ status = "launching"; executable = $BrowserExecutable } }
        Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).Browser -Message "Launching managed browser window."
        Write-RuntimeSceneEvent `
            -Component "browser" `
            -Phase "window" `
            -EventCode "browser.window.launch.requested" `
            -Message "Launching managed browser window." `
            -Outcome "started" `
            -Fields @{ executable = $BrowserExecutable }
    }
    $proc = Start-Process `
        -FilePath $BrowserExecutable `
        -ArgumentList $browserArgs `
        -WorkingDirectory $projectDir `
        -PassThru

    $windowProcess = Wait-ForBrowserWindow -LaunchProcessId $proc.Id
    if (-not $windowProcess) {
        Stop-ProcessesById (Get-ManagedBrowserPids)
        if ($script:currentRuntimeSceneId) {
            Update-RuntimeSceneManifest @{ browser = @{ status = "failed"; executable = $BrowserExecutable; launch_pid = $proc.Id; window_pid = 0 } }
            Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).Browser -Message "Managed browser window did not open successfully."
            Write-RuntimeSceneEvent `
                -Component "browser" `
                -Phase "window" `
                -EventCode "browser.window.launch.failed" `
                -Message "Managed browser window did not open successfully." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ executable = $BrowserExecutable; launch_pid = $proc.Id }
        }
        throw "Managed Edge app window did not open successfully."
    }

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ browser = @{ status = "open"; executable = $BrowserExecutable; launch_pid = $proc.Id; window_pid = $windowProcess.Id } }
        Append-RuntimeSceneRawLog -RelativePath (Get-RuntimeSceneRelativePaths).Browser -Message "Managed browser window opened (launch PID=$($proc.Id), window PID=$($windowProcess.Id))."
        Write-RuntimeSceneEvent `
            -Component "browser" `
            -Phase "window" `
            -EventCode "browser.window.opened" `
            -Message "Managed browser window opened." `
            -Outcome "succeeded" `
            -Fields @{ executable = $BrowserExecutable; launch_pid = $proc.Id; window_pid = $windowProcess.Id }
    }

    return [pscustomobject]@{
        LaunchPid = $proc.Id
        WindowPid = $windowProcess.Id
    }
}

function Start-Supervisor {
    param([string]$ManagedSessionId)

    $powershellExe = Join-Path $PSHOME "powershell.exe"
    if (-not (Test-Path $powershellExe)) {
        throw "PowerShell executable was not found at $powershellExe"
    }

    $supervisorLog = if ($script:currentRuntimeSceneId) {
        Get-CurrentRuntimeSceneFilePath (Get-RuntimeSceneRelativePaths).Supervisor
    } else {
        Join-Path $launcherDir "supervisor.log"
    }

    $proc = Start-Process `
        -FilePath $powershellExe `
        -ArgumentList @("-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath, "supervise", "-SessionId", $ManagedSessionId) `
        -WorkingDirectory $projectDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $supervisorLog `
        -PassThru

    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ supervisor = @{ pid = $proc.Id; status = "running" } }
        Write-RuntimeSceneEvent `
            -Component "supervisor" `
            -Phase "session" `
            -EventCode "supervisor.started" `
            -Message "Supervisor process started." `
            -Outcome "started" `
            -Fields @{ pid = $proc.Id; managed_session_id = $ManagedSessionId }
    }

    return $proc.Id
}

function Get-SessionSnapshot {
    $state = Get-State
    $backendPids = @(Get-ManagedBackendCandidatePids)
    $browserPids = @(Get-ManagedBrowserPids)
    $browserWindowProcesses = @(Get-ManagedBrowserWindowProcesses)

    $backendPid = $null
    if ($state -and $state.backendPid -and (Test-ProcessAlive ([int]$state.backendPid))) {
        $backendPid = [int]$state.backendPid
    } elseif ($backendPids.Count -gt 0) {
        $backendPid = [int]$backendPids[0]
    }

    $supervisorPid = $null
    if ($state -and $state.supervisorPid -and (Test-ProcessAlive ([int]$state.supervisorPid))) {
        $supervisorPid = [int]$state.supervisorPid
    }

    return [pscustomobject]@{
        State = $state
        BackendPid = $backendPid
        BackendPids = $backendPids
        BackendHealthy = [bool]($backendPid) -and (Test-WebHealthy)
        BrowserPids = $browserPids
        BrowserWindowProcesses = $browserWindowProcesses
        BrowserWindowCount = $browserWindowProcesses.Count
        BrowserWindowPid = if ($browserWindowProcesses.Count -gt 0) { [int]$browserWindowProcesses[0].Id } else { $null }
        SupervisorPid = $supervisorPid
        SessionRunning = [bool]($backendPid) -and (Test-WebHealthy) -and ($browserWindowProcesses.Count -gt 0)
    }
}

function Save-SessionState {
    param(
        [string]$ManagedSessionId,
        [int]$BackendPid,
        [pscustomobject]$PythonRuntime,
        [string]$BrowserExecutable,
        [int]$BrowserLaunchPid,
        [int]$BrowserWindowPid,
        [int]$SupervisorPid,
        [bool]$BrowserManaged
)

    $rawPaths = Get-RuntimeSceneRelativePaths
    Save-State @{
        mode = $mode
        sessionId = $ManagedSessionId
        host = $bindHost
        port = $port
        url = $url
        backendPid = $BackendPid
        backendStdout = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.BackendStdout } else { $null }
        backendStderr = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.BackendStderr } else { $null }
        pythonCommand = if ($PythonRuntime) { $PythonRuntime.FilePath } else { $null }
        pythonLabel = if ($PythonRuntime) { $PythonRuntime.Label } else { $null }
        browserManaged = $BrowserManaged
        browserExecutable = $BrowserExecutable
        browserProfileDir = $browserProfileDir
        browserLaunchPid = $BrowserLaunchPid
        browserWindowPid = $BrowserWindowPid
        supervisorPid = $SupervisorPid
        supervisorStdout = if ($script:currentRuntimeSceneDir) { Get-CurrentRuntimeSceneFilePath $rawPaths.Supervisor } else { $null }
        supervisorStderr = $null
        runtimeSceneId = $script:currentRuntimeSceneId
        runtimeSceneDir = $script:currentRuntimeSceneDir
        startedAt = (Get-Date).ToString("o")
    }
}

function Get-SessionReferenceTime {
    param([pscustomobject]$Snapshot)

    if ($Snapshot -and $Snapshot.BackendPid) {
        try {
            $backendProcess = Get-Process -Id $Snapshot.BackendPid -ErrorAction Stop
            return $backendProcess.StartTime.ToUniversalTime()
        } catch {
        }
    }

    if ($Snapshot -and $Snapshot.State -and $Snapshot.State.startedAt) {
        $parsed = [datetime]::MinValue
        if ([datetime]::TryParse([string]$Snapshot.State.startedAt, [ref]$parsed)) {
            return $parsed.ToUniversalTime()
        }
    }

    return [datetime]::MinValue
}

function Get-SessionRestartReason {
    param([pscustomobject]$Snapshot)

    if (-not $Snapshot) {
        return $null
    }

    $referenceTime = Get-SessionReferenceTime -Snapshot $Snapshot
    if ($referenceTime -eq [datetime]::MinValue) {
        return $null
    }

    $backendInputTime = Get-BackendInputTimeUtc
    if ($backendInputTime -gt $referenceTime) {
        return "backend files changed"
    }

    $frontendDistTime = Get-WebDistTimeUtc
    if ($frontendDistTime -gt $referenceTime) {
        return "frontend bundle changed"
    }

    return $null
}

function Adopt-Or-FocusSession {
    param([pscustomobject]$Snapshot)

    if (-not $Snapshot.SessionRunning) {
        return $false
    }

    if (-not $Snapshot.State -or -not $Snapshot.SupervisorPid) {
        Write-Note "Adopting a live managed session and reattaching supervision."
        if ($Snapshot.State -and $Snapshot.State.runtimeSceneId -and $Snapshot.State.runtimeSceneDir) {
            Set-CurrentRuntimeSceneContext -SceneId ([string]$Snapshot.State.runtimeSceneId) -SceneDir ([string]$Snapshot.State.runtimeSceneDir)
        }
        $managedSessionId = [guid]::NewGuid().ToString()
        $supervisorPid = Start-Supervisor -ManagedSessionId $managedSessionId
        Save-SessionState `
            -ManagedSessionId $managedSessionId `
            -BackendPid $Snapshot.BackendPid `
            -PythonRuntime $null `
            -BrowserExecutable $null `
            -BrowserLaunchPid 0 `
            -BrowserWindowPid $Snapshot.BrowserWindowPid `
            -SupervisorPid $supervisorPid `
            -BrowserManaged $true
    }

    Write-Note "Vibelution is already running. Focusing the existing app window."
    if ($Snapshot.State -and $Snapshot.State.runtimeSceneId -and $Snapshot.State.runtimeSceneDir) {
        Set-CurrentRuntimeSceneContext -SceneId ([string]$Snapshot.State.runtimeSceneId) -SceneDir ([string]$Snapshot.State.runtimeSceneDir)
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "session" `
            -EventCode "runtime.scene.focused" `
            -Message "Focused the existing managed session." `
            -Outcome "observed"
    }
    [void](Focus-ManagedBrowserWindow)
    return $true
}

function Stop-ManagedBrowserProcesses {
    $windowProcesses = @(Get-ManagedBrowserWindowProcesses)
    foreach ($windowProcess in $windowProcesses) {
        try {
            $null = $windowProcess.CloseMainWindow()
        } catch {
        }
    }
    Start-Sleep -Milliseconds 600
    Stop-ProcessesById (Get-ManagedBrowserPids)
}

function Stop-ManagedBackendProcesses {
    Stop-ProcessesById (Get-ManagedBackendCandidatePids)
}

function Get-ManagedSessionClosureSnapshot {
    $snapshot = Get-SessionSnapshot
    $workbench = Get-RuntimeManagerWorkbench
    $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
    $observedState = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
    $phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
    $failureMessage = [string](Get-ObjectPropertyValue -Object $workbench -Name "failureMessage" -Default "")
    $portOwnerPid = Get-ListeningPid $port
    $backendRunning = ($snapshot.BackendPids.Count -gt 0) -or [bool]$portOwnerPid -or (Test-WebHealthy)
    $browserRunning = ($snapshot.BrowserPids.Count -gt 0) -or ($snapshot.BrowserWindowCount -gt 0)
    $managerClosed = if ($workbench) {
        $desiredState -eq "closed" -and $observedState -eq "closed" -and $phase -eq "steady"
    } else {
        -not $backendRunning -and -not $browserRunning
    }

    return [pscustomobject]@{
        BackendStopped = -not $backendRunning
        BrowserStopped = -not $browserRunning
        ManagerClosed = [bool]$managerClosed
        BackendPids = @($snapshot.BackendPids)
        BrowserPids = @($snapshot.BrowserPids)
        BrowserWindowCount = [int]$snapshot.BrowserWindowCount
        PortOwnerPid = $portOwnerPid
        DesiredState = $desiredState
        ObservedState = $observedState
        Phase = $phase
        FailureMessage = $failureMessage
    }
}

function Test-ManagedSessionClosureSucceeded {
    param(
        [pscustomobject]$Closure,
        [bool]$RequireManagerClosed = $true
    )

    return [bool](
        $Closure `
        -and $Closure.BackendStopped `
        -and $Closure.BrowserStopped `
        -and ((-not $RequireManagerClosed) -or $Closure.ManagerClosed)
    )
}

function Write-ManagedSessionClosureRecord {
    param(
        [pscustomobject]$Closure,
        [string]$Reason,
        [string]$Source,
        [bool]$Success
    )

    $fields = @{
        reason = $Reason
        source = $Source
        backend_stopped = [bool]$Closure.BackendStopped
        browser_stopped = [bool]$Closure.BrowserStopped
        manager_closed = [bool]$Closure.ManagerClosed
        backend_pids = @($Closure.BackendPids)
        browser_pids = @($Closure.BrowserPids)
        browser_window_count = [int]$Closure.BrowserWindowCount
        port_owner_pid = $Closure.PortOwnerPid
        desired_state = [string]$Closure.DesiredState
        observed_state = [string]$Closure.ObservedState
        phase = [string]$Closure.Phase
        failure_message = [string]$Closure.FailureMessage
        control_log_path = $launcherControlLogPath
    }

    if ($script:currentRuntimeSceneId) {
        $finalState = if ($Success) {
            Get-RuntimeSceneFinalState -Reason $Reason
        } else {
            @{ status = "failed"; result = "shutdown_failed" }
        }
        Update-RuntimeSceneManifest @{
            status = $finalState.status
            result = $finalState.result
            stop_reason = $Reason
            ended_at = (Get-Date).ToUniversalTime().ToString("o")
            backend = @{
                health_status = if ($Closure.BackendStopped) { "stopped" } else { "failed_to_stop" }
                remaining_pids = @($Closure.BackendPids)
                port_owner_pid = $Closure.PortOwnerPid
            }
            browser = @{
                status = if ($Closure.BrowserStopped) { "stopped" } else { "failed_to_stop" }
                remaining_pids = @($Closure.BrowserPids)
            }
            launcher = @{
                control_log_path = (Get-RuntimeSceneRelativePaths).LauncherControl
                visible_monitor = if ($Source -eq "desktop_monitor") { if ($Success) { "closed" } else { "failed" } } else { "observed" }
                last_shutdown_source = $Source
            }
            runtime_manager = @{
                desired_state = [string]$Closure.DesiredState
                observed_state = [string]$Closure.ObservedState
                phase = [string]$Closure.Phase
                failure_message = [string]$Closure.FailureMessage
            }
        }
    }

    Write-LauncherControlLog `
        -Event $(if ($Success) { "launcher.shutdown.succeeded" } else { "launcher.shutdown.failed" }) `
        -Message $(if ($Success) { "Managed workbench shutdown completed." } else { "Managed workbench shutdown failed." }) `
        -Level $(if ($Success) { "info" } else { "error" }) `
        -Fields $fields
}

function Stop-ManagedSession {
    param([string]$Reason = "user requested stop")

    $snapshot = Get-SessionSnapshot
    if ($snapshot.BackendPids.Count -eq 0 -and $snapshot.BrowserPids.Count -eq 0 -and -not $snapshot.State) {
        Write-Note "No managed Vibelution session is running."
        return
    }

    $supervisorPid = $null
    if ($snapshot.State -and $snapshot.State.supervisorPid) {
        $supervisorPid = [int]$snapshot.State.supervisorPid
    }

    Write-Note "Stopping Vibelution session ($Reason)..."
    if ($snapshot.State -and $snapshot.State.runtimeSceneId -and $snapshot.State.runtimeSceneDir) {
        Set-CurrentRuntimeSceneContext -SceneId ([string]$snapshot.State.runtimeSceneId) -SceneDir ([string]$snapshot.State.runtimeSceneDir)
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "shutdown" `
            -EventCode "runtime.scene.stop.requested" `
            -Message "Stopping the managed session." `
            -Outcome "started" `
            -Fields @{ reason = $Reason }
        Update-RuntimeSceneManifest @{
            status = "stopping"
            stop_reason = $Reason
            browser = @{
                status = if ($snapshot.BrowserWindowCount -gt 0 -or $snapshot.BrowserPids.Count -gt 0) { "stopping" } else { "stopped" }
            }
            backend = @{
                health_status = if ($snapshot.BackendPid) { "stopping" } else { "stopped" }
            }
        }
    }
    Stop-ManagedBackendProcesses
    $backendStopped = Wait-ForPortClosed -Port $port

    if ($supervisorPid -and $supervisorPid -ne $selfProcessId) {
        Stop-ProcessesById @($supervisorPid)
    }

    $browserStopped = $true
    if ($backendStopped) {
        Stop-ManagedBrowserProcesses
        $browserStopped = Wait-ForBrowserStopped
    }

    $closure = Get-ManagedSessionClosureSnapshot
    if ($script:currentRuntimeSceneId) {
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "shutdown" `
            -EventCode "runtime.scene.stopped" `
            -Message "Managed session shutdown completed." `
            -Level $(if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false) { "info" } else { "warning" }) `
            -Outcome $(if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false) { "succeeded" } else { "partial" }) `
            -Fields @{
                reason = $Reason
                backend_stopped = [bool]$closure.BackendStopped
                browser_stopped = [bool]$closure.BrowserStopped
                manager_closed = [bool]$closure.ManagerClosed
                port_owner_pid = $closure.PortOwnerPid
            }
    }
    Write-ManagedSessionClosureRecord -Closure $closure -Reason $Reason -Source "launcher_stop" -Success (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false)

    if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $false) {
        Remove-State
        Write-Note "Vibelution session stopped."
        return
    }

    if (-not $browserStopped) {
        Write-Note "Managed browser processes are still winding down."
    }
    if (-not $backendStopped) {
        $portPid = Get-ListeningPid $port
        if ($portPid) {
            Write-Note "Port $port is still owned by PID=$portPid."
        }
        Write-Note "Keeping the browser window open until the backend stops."
    }

    $stopFailures = @()
    if (-not $backendStopped) {
        $stopFailures += "backend did not stop"
    }
    if (-not $browserStopped) {
        $stopFailures += "browser did not stop"
    }
    throw "Managed session did not stop cleanly: $($stopFailures -join '; ')."
}

function Show-Status {
    $snapshot = Get-SessionSnapshot
    $buildReason = Get-WebBuildReason
    $sessionRestartReason = Get-SessionRestartReason -Snapshot $snapshot

    Write-Host "Mode      : $mode"
    Write-Host "Project   : $projectDir"
    Write-Host "URL       : $url"

    if ($snapshot.BackendPid) {
        $backendHealth = if ($snapshot.BackendHealthy) { "healthy" } else { "starting or unhealthy" }
        Write-Host "Backend   : running (PID=$($snapshot.BackendPid), $backendHealth)"
    } else {
        Write-Host "Backend   : stopped"
    }

    if ($snapshot.BrowserWindowCount -gt 0) {
        Write-Host "Browser   : running (window PID=$($snapshot.BrowserWindowPid), managed windows=$($snapshot.BrowserWindowCount))"
    } elseif ($snapshot.BrowserPids.Count -gt 0) {
        Write-Host "Browser   : background only (PID(s)=$($snapshot.BrowserPids -join ', '))"
    } else {
        Write-Host "Browser   : stopped"
    }

    if ($snapshot.SupervisorPid) {
        Write-Host "Supervisor: running (PID=$($snapshot.SupervisorPid))"
    } else {
        Write-Host "Supervisor: stopped"
    }

    if ($snapshot.SessionRunning) {
        if ($sessionRestartReason) {
            Write-Host "Session   : stale ($sessionRestartReason)"
        } else {
            Write-Host "Session   : current"
        }
    } elseif ($snapshot.BackendPids.Count -gt 0 -or $snapshot.BrowserPids.Count -gt 0 -or $snapshot.State) {
        Write-Host "Session   : incomplete (cleanup required before next launch)"
    } else {
        Write-Host "Session   : stopped"
    }

    if ($buildReason) {
        Write-Host "Frontend  : stale ($buildReason)"
    } else {
        Write-Host "Frontend  : current"
    }

    if ($snapshot.State) {
        Write-Host "State     : $statePath"
        if ($snapshot.State.runtimeSceneId) {
            Write-Host "Scene     : $($snapshot.State.runtimeSceneId)"
        }
        if ($snapshot.State.backendStdout) {
            Write-Host "Logs      : $($snapshot.State.backendStdout)"
        }
        if ($snapshot.State.backendStderr) {
            Write-Host "Errors    : $($snapshot.State.backendStderr)"
        }
    } else {
        Write-Host "State     : not tracking a managed session"
    }
}

function Start-ManagedSession {
    Ensure-Directories

    $snapshot = Get-SessionSnapshot
    $restartReason = Get-SessionRestartReason -Snapshot $snapshot

    if ($snapshot.SessionRunning -and -not $restartReason) {
        if (Adopt-Or-FocusSession -Snapshot $snapshot) {
            return
        }
    } elseif ($snapshot.SessionRunning -and $restartReason) {
        Write-Note "Restarting the managed session because $restartReason."
        Stop-ManagedSession -Reason $restartReason
        $snapshot = Get-SessionSnapshot
    }

    if ($snapshot.BackendPids.Count -gt 0 -or $snapshot.BrowserPids.Count -gt 0 -or $snapshot.State) {
        Write-Note "Found an incomplete managed session. Cleaning it up before restart."
        Stop-ManagedSession -Reason "cleanup stale session"
    }

    $portPid = Get-ListeningPid $port
    if ($portPid) {
        throw "Port $port is already in use by PID=$portPid. Stop that process first."
    }

    Initialize-RuntimeScene -Trigger $Action -BrowserManaged (-not $NoBrowser)

    try {
        Ensure-WebBuild
        Ensure-ProjectPythonDependencies

        $pythonRuntime = Resolve-PythonRuntime
        $managedSessionId = [guid]::NewGuid().ToString()
        $backendProc = Start-ManagedBackend -PythonRuntime $pythonRuntime

        if ($NoBrowser) {
            Save-SessionState `
                -ManagedSessionId $managedSessionId `
                -BackendPid $backendProc.Id `
                -PythonRuntime $pythonRuntime `
                -BrowserExecutable $null `
                -BrowserLaunchPid 0 `
                -BrowserWindowPid 0 `
                -SupervisorPid 0 `
                -BrowserManaged $false
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "session" `
                -EventCode "runtime.scene.backend_live" `
                -Message "Managed backend is live without a browser window." `
                -Outcome "succeeded" `
                -Fields @{ url = $url; backend_pid = $backendProc.Id }
            Write-Note "Vibelution backend is live at $url"
            return
        }

        $browserExecutable = Resolve-EdgeExecutable
        $browserInfo = Start-ManagedBrowser -BrowserExecutable $browserExecutable

        Save-SessionState `
            -ManagedSessionId $managedSessionId `
            -BackendPid $backendProc.Id `
            -PythonRuntime $pythonRuntime `
            -BrowserExecutable $browserExecutable `
            -BrowserLaunchPid $browserInfo.LaunchPid `
            -BrowserWindowPid $browserInfo.WindowPid `
            -SupervisorPid 0 `
            -BrowserManaged $true

        $supervisorPid = Start-Supervisor -ManagedSessionId $managedSessionId

        Save-SessionState `
            -ManagedSessionId $managedSessionId `
            -BackendPid $backendProc.Id `
            -PythonRuntime $pythonRuntime `
            -BrowserExecutable $browserExecutable `
            -BrowserLaunchPid $browserInfo.LaunchPid `
            -BrowserWindowPid $browserInfo.WindowPid `
            -SupervisorPid $supervisorPid `
            -BrowserManaged $true

        [void](Focus-ManagedBrowserWindow)
        Write-RuntimeSceneEvent `
            -Component "launcher" `
            -Phase "session" `
            -EventCode "runtime.scene.ready" `
            -Message "Managed runtime scene is ready." `
            -Outcome "succeeded" `
            -Fields @{ url = $url; backend_pid = $backendProc.Id; browser_window_pid = $browserInfo.WindowPid; supervisor_pid = $supervisorPid }
        Write-Note "Vibelution is live in a managed Edge app window at $url"
    } catch {
        if ($script:currentRuntimeSceneId) {
            Write-RuntimeSceneEvent `
                -Component "launcher" `
                -Phase "session" `
                -EventCode "runtime.scene.startup.failed" `
                -Message "Managed runtime scene startup failed." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{ reason = $_.Exception.Message }
            Update-RuntimeSceneManifest @{
                status = "failed"
                result = "startup_failed"
                stop_reason = $_.Exception.Message
                ended_at = (Get-Date).ToUniversalTime().ToString("o")
            }
        }
        Stop-ManagedBrowserProcesses
        Stop-ManagedBackendProcesses
        Remove-State
        throw
    }
}

function Run-SupervisorLoop {
    param([string]$ManagedSessionId)

    if (-not $ManagedSessionId) {
        throw "Supervisor mode requires -SessionId."
    }

    while ($true) {
        $state = Get-State
        if (-not $state) {
            return
        }
        if ($state.sessionId -ne $ManagedSessionId) {
            return
        }

        $backendAlive = $false
        if ($state.backendPid) {
            $backendAlive = Test-ProcessAlive ([int]$state.backendPid)
        }

        $browserWindowCount = @(Get-ManagedBrowserWindowProcesses).Count

        if (-not $backendAlive) {
            Write-Note "Supervisor detected backend exit. Closing the managed app window."
            Stop-ManagedSession -Reason "backend exited unexpectedly"
            return
        }

        if ([bool]$state.browserManaged -and $browserWindowCount -eq 0) {
            Write-Note "Supervisor detected app window closure. Stopping the backend."
            Stop-ManagedSession -Reason "app window closed"
            return
        }

        Start-Sleep -Milliseconds 900
    }
}

function Invoke-DesktopLifecycleMonitor {
    param(
        [int]$OpenTimeoutSeconds = 60,
        [int]$CloseTimeoutSeconds = 120,
        [int]$SuccessExitDelaySeconds = 2
    )

    Ensure-Directories
    Sync-LauncherEndpointFromState
    [void](Restore-RuntimeSceneContextFromState)

    Write-Note "Launcher monitor attached. Close the workbench from the web UI or this window will report the final shutdown status."
    if ($script:currentRuntimeSceneId) {
        Update-RuntimeSceneManifest @{ launcher = @{ visible_monitor = "running"; control_log_path = (Get-RuntimeSceneRelativePaths).LauncherControl } }
    }
    Write-LauncherMonitorEvent `
        -EventCode "launcher.monitor.started" `
        -Message "Visible launcher monitor attached to the managed workbench lifecycle." `
        -Outcome "started" `
        -Fields @{ open_timeout_seconds = $OpenTimeoutSeconds; close_timeout_seconds = $CloseTimeoutSeconds; control_log_path = $launcherControlLogPath }

    $opened = Wait-ForRuntimeManagerWorkbenchOpen -TimeoutSeconds $OpenTimeoutSeconds
    if (-not $opened) {
        [void](Restore-RuntimeSceneContextFromState)
        $workbench = Get-RuntimeManagerWorkbench
        $message = "Workbench did not reach open/steady before launcher monitor timeout."
        $fields = @{
            desired_state = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
            observed_state = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
            phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
            failure_message = [string](Get-ObjectPropertyValue -Object $workbench -Name "failureMessage" -Default "")
        }
        Write-LauncherMonitorEvent `
            -EventCode "launcher.monitor.open_timeout" `
            -Message $message `
            -Level "error" `
            -Outcome "failed" `
            -Fields $fields
        throw $message
    }

    [void](Restore-RuntimeSceneContextFromState)
    Write-Note "Workbench is running. Waiting for shutdown request ..."
    Write-LauncherMonitorEvent `
        -EventCode "launcher.monitor.workbench_open" `
        -Message "Workbench reached open/steady; waiting for lifecycle shutdown." `
        -Outcome "succeeded"

    $seenClosing = $false
    $closeDeadline = $null
    $lastPhase = ""
    while ($true) {
        [void](Restore-RuntimeSceneContextFromState)
        $workbench = Get-RuntimeManagerWorkbench
        $desiredState = [string](Get-ObjectPropertyValue -Object $workbench -Name "desiredState" -Default "")
        $observedState = [string](Get-ObjectPropertyValue -Object $workbench -Name "observedState" -Default "")
        $phase = [string](Get-ObjectPropertyValue -Object $workbench -Name "phase" -Default "")
        $failureMessage = [string](Get-ObjectPropertyValue -Object $workbench -Name "failureMessage" -Default "")

        if ($phase -and $phase -ne $lastPhase) {
            $lastPhase = $phase
            Write-LauncherControlLog `
                -Event "launcher.monitor.phase" `
                -Message "Runtime manager phase changed." `
                -Fields @{ desired_state = $desiredState; observed_state = $observedState; phase = $phase }
        }

        if ($phase -eq "failed") {
            $closure = Get-ManagedSessionClosureSnapshot
            $closureReason = Get-RuntimeManagerWorkbenchReason -Workbench $workbench -Fallback "runtime manager failure"
            $closureSource = Get-RuntimeManagerWorkbenchSource -Workbench $workbench -Fallback "desktop_monitor"
            Write-ManagedSessionClosureRecord -Closure $closure -Reason $closureReason -Source $closureSource -Success $false
            Write-LauncherMonitorEvent `
                -EventCode "launcher.monitor.failed" `
                -Message "Runtime manager reported a lifecycle failure." `
                -Level "error" `
                -Outcome "failed" `
                -Fields @{
                    desired_state = $desiredState
                    observed_state = $observedState
                    phase = $phase
                    failure_message = $failureMessage
                    backend_stopped = [bool]$closure.BackendStopped
                    browser_stopped = [bool]$closure.BrowserStopped
                    manager_closed = [bool]$closure.ManagerClosed
                    port_owner_pid = $closure.PortOwnerPid
                }
            throw "Workbench lifecycle failed: $failureMessage"
        }

        if (-not $seenClosing -and $desiredState -eq "closed") {
            $seenClosing = $true
            $closeDeadline = (Get-Date).AddSeconds($CloseTimeoutSeconds)
            Write-Note "Shutdown requested. Waiting for backend and browser to close ..."
            Write-LauncherMonitorEvent `
                -EventCode "launcher.monitor.shutdown_detected" `
                -Message "Launcher monitor detected a workbench shutdown request." `
                -Outcome "observed" `
                -Fields @{ desired_state = $desiredState; observed_state = $observedState; phase = $phase }
        }

        if ($seenClosing) {
            $closure = Get-ManagedSessionClosureSnapshot
            if (Test-ManagedSessionClosureSucceeded -Closure $closure -RequireManagerClosed $true) {
                $closureReason = Get-RuntimeManagerWorkbenchReason -Workbench $workbench -Fallback "workbench closed"
                $closureSource = Get-RuntimeManagerWorkbenchSource -Workbench $workbench -Fallback "desktop_monitor"
                Write-ManagedSessionClosureRecord -Closure $closure -Reason $closureReason -Source $closureSource -Success $true
                Write-LauncherMonitorEvent `
                    -EventCode "launcher.monitor.shutdown_confirmed" `
                    -Message "Backend, browser, and runtime manager all report closed." `
                    -Outcome "succeeded" `
                    -Fields @{
                        backend_stopped = [bool]$closure.BackendStopped
                        browser_stopped = [bool]$closure.BrowserStopped
                        manager_closed = [bool]$closure.ManagerClosed
                        port_owner_pid = $closure.PortOwnerPid
                    }
                Write-Note "Backend stopped."
                Write-Note "Browser stopped."
                Write-Note "Workbench closed cleanly."
                Write-Note "Launcher will close in $SuccessExitDelaySeconds seconds."
                Start-Sleep -Seconds $SuccessExitDelaySeconds
                return
            }

            if ($closeDeadline -and (Get-Date) -gt $closeDeadline) {
                Write-ManagedSessionClosureRecord -Closure $closure -Reason "desktop monitor shutdown timeout" -Source "desktop_monitor" -Success $false
                Write-LauncherMonitorEvent `
                    -EventCode "launcher.monitor.shutdown_timeout" `
                    -Message "Shutdown did not complete before launcher monitor timeout." `
                    -Level "error" `
                    -Outcome "failed" `
                    -Fields @{
                        backend_stopped = [bool]$closure.BackendStopped
                        browser_stopped = [bool]$closure.BrowserStopped
                        manager_closed = [bool]$closure.ManagerClosed
                        backend_pids = @($closure.BackendPids)
                        browser_pids = @($closure.BrowserPids)
                        port_owner_pid = $closure.PortOwnerPid
                        desired_state = [string]$closure.DesiredState
                        observed_state = [string]$closure.ObservedState
                        phase = [string]$closure.Phase
                    }
                throw "Workbench shutdown timed out. See $launcherControlLogPath for details."
            }
        }

        Start-Sleep -Milliseconds 750
    }
}

$runtimeManagerClientActions = @("toggle", "start", "stop", "restart", "status")
if ($runtimeManagerClientActions -contains $Action) {
    switch ($Action) {
        "toggle" {
            Invoke-RuntimeManagerClient -Mode "command" -CommandType "toggle_workbench" -Reason "launcher_toggle" -ForwardNoBrowser:$NoBrowser
        }
        "start" {
            Invoke-RuntimeManagerClient -Mode "command" -CommandType "open_workbench" -Reason "launcher_start" -ForwardNoBrowser:$NoBrowser
        }
        "stop" {
            Invoke-RuntimeManagerClient -Mode "command" -CommandType "close_workbench" -Reason "launcher_stop"
        }
        "restart" {
            Invoke-RuntimeManagerClient -Mode "command" -CommandType "restart_workbench" -Reason "launcher_restart" -ForwardNoBrowser:$NoBrowser
        }
        "status" {
            Invoke-RuntimeManagerClient -Mode "status"
        }
    }
    return
}

Acquire-LauncherMutex
try {
    Sync-LauncherEndpointFromState
    switch ($Action) {
        "toggle" {
            $snapshot = Get-SessionSnapshot
            if ($snapshot.BackendPids.Count -gt 0 -or $snapshot.BrowserPids.Count -gt 0 -or $snapshot.State) {
                Stop-ManagedSession -Reason "toggle stop"
            } else {
                Start-ManagedSession
            }
        }
        "internal-start" {
            Start-ManagedSession
        }
        "start" {
            Start-ManagedSession
        }
        "internal-stop" {
            Stop-ManagedSession -Reason "runtime manager stop"
        }
        "stop" {
            Stop-ManagedSession -Reason "explicit stop"
        }
        "internal-restart" {
            Stop-ManagedSession -Reason "runtime manager restart"
            Start-ManagedSession
        }
        "monitor" {
            Invoke-DesktopLifecycleMonitor
        }
        "restart" {
            Stop-ManagedSession -Reason "restart"
            Start-ManagedSession
        }
        "internal-status" {
            Show-Status
        }
        "status" {
            Show-Status
        }
        "supervise" {
            Run-SupervisorLoop -ManagedSessionId $SessionId
        }
    }
} finally {
    Release-LauncherMutex
}
