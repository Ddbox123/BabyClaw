param(
    [switch]$Json,
    [string]$ProjectRoot = $(Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

function New-CheckResult {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail = ""
    )

    [PSCustomObject]@{
        name = $Name
        ok = $Ok
        detail = $Detail
    }
}

$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$expectedPython = Join-Path $resolvedRoot ".venv\Scripts\python.exe"
$selectedPython = $expectedPython

if (-not (Test-Path $selectedPython)) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCmd) {
        $selectedPython = $pythonCmd.Source
    }
}

$venvOk = Test-Path $expectedPython

$criticalModules = @(
    "rich",
    "pydantic",
    "langchain_openai",
    "pytest_asyncio"
)

$imports = @()
foreach ($moduleName in $criticalModules) {
    & $selectedPython -c "import $moduleName" 2>$null
    $imports += [PSCustomObject]@{
        name = $moduleName
        ok = ($LASTEXITCODE -eq 0)
    }
}
$pytestVersion = & $selectedPython -m pytest --version
$pytestOk = $LASTEXITCODE -eq 0

$importChecksOk = (($imports | Where-Object { -not $_.ok }).Count -eq 0)
$allChecksOk = $venvOk -and $pytestOk -and $importChecksOk

$report = [PSCustomObject]@{
    ok = $allChecksOk
    project_root = $resolvedRoot
    python = [PSCustomObject]@{
        expected = $expectedPython
        selected = $selectedPython
        using_venv = ($selectedPython -eq $expectedPython)
    }
    checks = [PSCustomObject]@{
        venv = [PSCustomObject]@{
            ok = $venvOk
            path = $expectedPython
        }
        imports = @($imports)
        pytest_module = [PSCustomObject]@{
            ok = $pytestOk
            version = ($pytestVersion -join "`n")
        }
    }
}

if ($Json) {
    $report | ConvertTo-Json -Depth 6
    exit 0
}

Write-Host "== Vibelution Environment Doctor =="
Write-Host "ProjectRoot : $($report.project_root)"
Write-Host "Python      : $($report.python.selected)"
Write-Host "Venv        : $(if ($report.checks.venv.ok) { 'OK' } else { 'MISSING' })"

foreach ($item in $report.checks.imports) {
    Write-Host ("Import {0,-18}: {1}" -f $item.name, $(if ($item.ok) { "OK" } else { "FAIL" }))
}

Write-Host "Pytest      : $(if ($report.checks.pytest_module.ok) { $report.checks.pytest_module.version } else { 'FAIL' })"
if ($report.ok) {
    exit 0
}
exit 1
