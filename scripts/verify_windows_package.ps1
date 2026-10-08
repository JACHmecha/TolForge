[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PackageDirectory,
    [Parameter(Mandatory)][ValidateSet('scalar', 'cad')][string]$Profile,
    [Parameter(Mandatory)][string]$OutputDirectory
)

# Runs on the target with PowerShell and Windows only; no Python/Conda required.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$output = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'Choose a new empty output directory for each qualification run.' }
New-Item -ItemType Directory -Path $output | Out-Null
$report = [ordered]@{
    schema_version = 1
    profile = $Profile
    status = 'failed'
    started_utc = [DateTime]::UtcNow.ToString('o')
    machine_scope = 'isolated-workstation'
    windows_version = [Environment]::OSVersion.VersionString
    architecture = $env:PROCESSOR_ARCHITECTURE
    verifier_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    executable_sha256 = $null
    verified_files = @()
    smoke = $null
}
if ($env:GITHUB_ACTIONS -eq 'true') {
    $report.machine_scope = 'separate-hosted-windows-runner'
    $report.workflow_run = $env:GITHUB_RUN_ID
    $report.workflow_job = $env:GITHUB_JOB
    $report.runner_image = $env:ImageVersion
}
$saved = @{}
$variables = @('PATH', 'LOCALAPPDATA', 'APPDATA', 'USERPROFILE', 'HOME', 'CONDA_PREFIX',
    'CONDA_DEFAULT_ENV', 'CONDA_ROOT', 'PYTHONPATH', 'PYTHONHOME', 'TOLFORGE_DLL_DIRS',
    'QT_QPA_PLATFORM', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH',
    'QT_OPENGL', 'QT_OPENGL_DLL', 'QT_OPENGL_BUGLIST', 'QT_NO_OPENGL_BUGLIST',
    'QT_ANGLE_PLATFORM', 'PYOPENGL_PLATFORM')
$process = $null
try {
    $hashes = Get-Content -LiteralPath (Join-Path $package 'SHA256.json') -Raw | ConvertFrom-Json
    if ($hashes.schema_version -ne 1 -or $hashes.profile -ne $Profile -or @($hashes.files).Count -eq 0) {
        throw 'Package hash manifest has an unsupported schema or incorrect profile.'
    }
    $seen = @{}
    foreach ($entry in $hashes.files) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative)) {
            throw 'Manifest paths must be relative package files.'
        }
        $file = [IO.Path]::GetFullPath((Join-Path $package $relative))
        if (-not $file.StartsWith($package.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Manifest path escapes the package directory.'
        }
        if ($seen.ContainsKey($file)) { throw 'Manifest repeats a package file.' }
        $seen[$file] = $true
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "Package hash mismatch: $relative" }
        $report.verified_files += $relative
        if ($relative -eq 'TolForge.exe') { $report.executable_sha256 = $actual }
    }
    $requiredEvidence = @('TolForge.exe', 'tolforge-build.json', 'build-provenance.json', 'packaged-smoke.json', 'pip-freeze.txt', 'windows-release-py312.lock')
    if ($Profile -eq 'cad') { $requiredEvidence += @('native-dependencies.json', 'windows-cad-py312.lock', 'conda-explicit-win-64.txt') }
    foreach ($required in $requiredEvidence) {
        if ($report.verified_files -notcontains $required) { throw "Hash manifest omits required evidence: $required" }
    }
    $metadata = Get-Content -LiteralPath (Join-Path $package 'tolforge-build.json') -Raw | ConvertFrom-Json
    if ($metadata.profile -ne $Profile) { throw 'Package metadata does not match the selected profile.' }
    if ($Profile -eq 'cad') {
        $nativeHash = (Get-FileHash -LiteralPath (Join-Path $package 'native-dependencies.json') -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($metadata.PSObject.Properties.Name -notcontains 'native_dependencies_sha256' -or
            $nativeHash -ne $metadata.native_dependencies_sha256) {
            throw 'Native dependency manifest does not match build metadata.'
        }
    }
    if ($metadata.PSObject.Properties.Name -contains 'conda_runtime_manifest_sha256') {
        foreach ($required in @('native-conda-runtime.json', 'conda-explicit-win-64.txt')) {
            if ($report.verified_files -notcontains $required) { throw "Hash manifest omits locked interpreter evidence: $required" }
        }
        $runtimeHash = (Get-FileHash -LiteralPath (Join-Path $package 'native-conda-runtime.json') -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($runtimeHash -ne $metadata.conda_runtime_manifest_sha256) { throw 'Locked interpreter manifest does not match build metadata.' }
    }
    $report.source_revision = $metadata.source_revision
    # Copy only the executable to a detached folder. Sidecar build data is embedded
    # in the executable, so importing source/evidence from the checkout cannot help.
    $install = Join-Path $output 'installed'
    New-Item -ItemType Directory -Path $install | Out-Null
    $executable = Join-Path $install 'TolForge.exe'
    Copy-Item -LiteralPath (Join-Path $package 'TolForge.exe') -Destination $executable
    foreach ($name in $variables) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:LOCALAPPDATA = Join-Path $output 'user\Local'
    $env:APPDATA = Join-Path $output 'user\Roaming'
    $env:USERPROFILE = Join-Path $output 'user'
    foreach ($folder in @($env:LOCALAPPDATA, $env:APPDATA)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
    }
    $smokePath = Join-Path $output 'target-smoke.json'
    $arguments = @('--self-check-json', ('"' + $smokePath + '"'), '--expected-profile', $Profile)
    if ($Profile -eq 'cad') { $arguments += @('--self-check-cad', '--self-check-viewport') }
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $install -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(180000)) {
        $process.Kill()
        $process.WaitForExit()
        throw 'Target executable qualification timed out.'
    }
    if (-not (Test-Path -LiteralPath $smokePath)) { throw "Target executable produced no report (exit $($process.ExitCode))." }
    $smoke = Get-Content -LiteralPath $smokePath -Raw | ConvertFrom-Json
    $report.smoke = $smoke
    if ($process.ExitCode -ne 0 -or $smoke.status -ne 'ok' -or $smoke.frozen -ne $true -or $smoke.profile -ne $Profile) {
        throw 'Target executable failed its frozen profile checks; inspect target-smoke.json.'
    }
    # The executable must report the same build identity as its hashed sidecar.
    if ($smoke.executable.sha256 -ne $report.executable_sha256) { throw 'The target report describes a different executable.' }
    $embeddedMetadata = $smoke.build_metadata | ConvertTo-Json -Depth 30 -Compress
    $sidecarMetadata = $metadata | ConvertTo-Json -Depth 30 -Compress
    if ($embeddedMetadata -cne $sidecarMetadata) {
        throw 'Embedded and sidecar build provenance differ.'
    }
    if ($Profile -eq 'cad' -and $smoke.viewport.status -ne 'ok') { throw 'Native viewport qualification did not pass.' }
    $report.status = 'ok'
} catch {
    $report.error = $_.Exception.Message
} finally {
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name], 'Process') }
    if ($null -ne $process) { $process.Dispose() }
    $report.finished_utc = [DateTime]::UtcNow.ToString('o')
    $report | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $output 'target-qualification.json') -Encoding utf8
}
if ($report.status -ne 'ok') { throw $report.error }
Write-Host "Verified $Profile executable on $($report.machine_scope): $($report.executable_sha256)"
