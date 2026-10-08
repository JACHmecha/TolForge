[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$SelfCheckJson,
    [switch]$IncludeCad,
    [switch]$QualifyViewport
)

$ErrorActionPreference = 'Stop'
$application = Join-Path $PSScriptRoot 'Code\gui\app.py'
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "Application source is missing from this checkout: $application"
}
if ($IncludeCad -and -not $SelfCheckJson) {
    throw '-IncludeCad requires -SelfCheckJson for an explicit CAD qualification check.'
}
if ($QualifyViewport -and (-not $SelfCheckJson -or -not $IncludeCad)) {
    throw '-QualifyViewport requires -SelfCheckJson and -IncludeCad.'
}

$interpreter = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$arguments = @($application)
if ($SelfCheckJson) {
    # Interpret a relative report path against the calling directory, before
    # switching to this checkout. The application always comes from this script.
    $report = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($SelfCheckJson)
    $arguments += @('--self-check-json', $report)
    if ($IncludeCad) { $arguments += '--self-check-cad' }
    if ($QualifyViewport) { $arguments += '--self-check-viewport' }
}

Write-Host "TolForge source: $application"
Write-Host "Python interpreter: $interpreter"
Push-Location $PSScriptRoot
try {
    & $interpreter @arguments
    $applicationExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $applicationExitCode
