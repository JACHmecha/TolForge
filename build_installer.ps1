[CmdletBinding()]
param(
    [string]$Python = 'python',
    [switch]$SkipDependencyInstall,
    [switch]$IncludeCad
)

$ErrorActionPreference = 'Stop'
$profile = if ($IncludeCad) { 'cad' } else { 'scalar' }
$interpreter = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$releaseLock = Join-Path $PSScriptRoot '.github\environments\windows-release-py312.lock'
$cadLock = Join-Path $PSScriptRoot '.github\environments\windows-cad-py312.lock'
$nativeLock = Join-Path $PSScriptRoot '.github\environments\native-cad-win-64.conda.lock'
$scalarLock = Join-Path $PSScriptRoot '.github\environments\scalar-win-64.conda.lock'
$helper = Join-Path $PSScriptRoot 'scripts\windows_build.py'
$workRoot = Join-Path $PSScriptRoot ".tolforge\build\$profile"
$runRoot = Join-Path $workRoot ([Guid]::NewGuid().ToString('N'))
$artifact = Join-Path $runRoot 'artifact'
$destination = Join-Path $PSScriptRoot "dist\$profile"
$savedEnvironment = @{}
foreach ($name in @('TOLFORGE_BUILD_CAD', 'TOLFORGE_BUILD_METADATA', 'QT_QPA_PLATFORM', 'TOLFORGE_DLL_DIRS', 'CONDA_PREFIX', 'PYTHONPATH', 'TOLFORGE_WINDOWS_BUILD_BOOTSTRAP')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

Push-Location $PSScriptRoot
try {
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $artifact -Force | Out-Null
    # CAD interpreters are prepared from native-cad-win-64.conda.lock first. This
    # build never borrows a separately configured workstation CAD installation.
    & $interpreter -c 'import sys; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32, "Use Windows x64 Python 3.12 and the release dependency lock."'
    if ($LASTEXITCODE -ne 0) { throw 'The release interpreter is not Windows x64 Python 3.12.' }
    if (-not $SkipDependencyInstall) {
        Write-Host "Installing the hash-locked $profile build dependencies..."
        & $interpreter -m pip install --require-hashes --only-binary=:all: --report (Join-Path $artifact 'pip-install-report.json') -r $releaseLock
        if ($LASTEXITCODE -ne 0) { throw 'Locked desktop dependency installation failed.' }
        if ($IncludeCad) {
            & $interpreter -m pip install --require-hashes --no-deps --no-build-isolation --report (Join-Path $artifact 'cad-install-report.json') -r $cadLock
            if ($LASTEXITCODE -ne 0) { throw 'Locked CAD wrapper installation failed.' }
        }
        & $interpreter -m pip install --no-deps --no-build-isolation .
        if ($LASTEXITCODE -ne 0) { throw 'Local project installation failed.' }
    }
    & $interpreter -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'The selected build environment has inconsistent dependencies.' }
    & $interpreter $helper prepare --root $PSScriptRoot --output $artifact --profile $profile
    if ($LASTEXITCODE -ne 0) { throw 'The build environment or source provenance could not be verified.' }

    if ($IncludeCad) {
        $nativePrefix = (& $interpreter -c 'import sys; print(sys.prefix)').Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cannot determine the CAD interpreter prefix.' }
        $env:CONDA_PREFIX = $nativePrefix
        $env:TOLFORGE_DLL_DIRS = Join-Path $nativePrefix 'Library\bin'
    }
    # PYTHONPATH is inherited by PyInstaller's isolated import workers. Its
    # narrowly enabled sitecustomize pins the Windows ICU ABI before any Qt
    # import, including pytest's early GUI fixtures and Qt library inspection.
    $env:TOLFORGE_WINDOWS_BUILD_BOOTSTRAP = '1'
    $env:PYTHONPATH = (Join-Path $PSScriptRoot 'scripts\windows_bootstrap') + [System.IO.Path]::PathSeparator + (Join-Path $PSScriptRoot 'Code')

    $env:QT_QPA_PLATFORM = 'offscreen'
    $testArgs = @('-m', 'pytest', 'tests', '-q', '--strict-markers', "--junitxml=$(Join-Path $artifact 'tests.xml')")
    if ($IncludeCad) { $testArgs += '--require-native-cad' } else { $testArgs += @('-m', 'not native_cad') }
    & $interpreter @testArgs
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; the executable was not built.' }

    $env:TOLFORGE_BUILD_CAD = if ($IncludeCad) { '1' } else { '0' }
    $env:TOLFORGE_BUILD_METADATA = Join-Path $artifact 'tolforge-build.json'
    Write-Host "Building the $profile executable with $interpreter..."
    & $interpreter -m PyInstaller --clean --noconfirm --distpath $artifact --workpath (Join-Path $runRoot 'pyinstaller') TolForge.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    $executable = Join-Path $artifact 'TolForge.exe'
    if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw 'Executable is missing.' }
    & $interpreter $helper verify-source --root $PSScriptRoot --output $artifact --profile $profile
    if ($LASTEXITCODE -ne 0) { throw 'Source files changed during the build; the executable was not qualified.' }

    & $interpreter -m pip freeze | Set-Content -LiteralPath (Join-Path $artifact 'pip-freeze.txt') -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw 'Dependency manifest generation failed.' }
    Copy-Item -LiteralPath $releaseLock -Destination (Join-Path $artifact 'windows-release-py312.lock') -Force
    if ($IncludeCad) {
        Copy-Item -LiteralPath $cadLock -Destination (Join-Path $artifact 'windows-cad-py312.lock') -Force
        Copy-Item -LiteralPath $nativeLock -Destination (Join-Path $artifact 'conda-explicit-win-64.txt') -Force
    } elseif (Test-Path -LiteralPath (Join-Path $artifact 'native-conda-runtime.json')) {
        Copy-Item -LiteralPath $scalarLock -Destination (Join-Path $artifact 'conda-explicit-win-64.txt') -Force
    }
    # Exact executable, no Python/conda/native paths, fresh per-user configuration.
    # The separate portable verifier records the scope of clean-Windows evidence.
    $smokeEnvironment = @{}
    $resetNames = @('PATH', 'LOCALAPPDATA', 'APPDATA', 'PYTHONPATH', 'PYTHONHOME', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV',
                    'TOLFORGE_DLL_DIRS', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH')
    foreach ($name in $resetNames) {
        $smokeEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }
    try {
        $isolatedUser = Join-Path $runRoot 'isolated-user'
        New-Item -ItemType Directory -Path $isolatedUser -Force | Out-Null
        $env:LOCALAPPDATA = $isolatedUser
        $env:APPDATA = $isolatedUser
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $reportPath = Join-Path $artifact 'packaged-smoke.json'
        if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath }
        $smokeArgs = @('--self-check-json', "`"$reportPath`"", '--expected-profile', $profile)
        if ($IncludeCad) { $smokeArgs += '--self-check-cad' }
        $process = Start-Process -FilePath $executable -ArgumentList $smokeArgs -WorkingDirectory $isolatedUser -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit(120000)) {
            $process.Kill()
            throw 'Packaged smoke check timed out.'
        }
        if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
            throw "Packaged smoke check failed; inspect $reportPath if present."
        }
        $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
        if ($report.status -ne 'ok' -or $report.frozen -ne $true -or $report.profile -ne $profile) {
            throw 'Packaged smoke report did not qualify the expected frozen profile.'
        }
    } finally {
        foreach ($name in $resetNames) { [Environment]::SetEnvironmentVariable($name, $smokeEnvironment[$name], 'Process') }
    }
    & $interpreter $helper finalize --output $artifact --profile $profile
    if ($LASTEXITCODE -ne 0) { throw 'Artifact checksum manifest generation failed.' }
    & $interpreter $helper verify-source --root $PSScriptRoot --output $artifact --profile $profile
    if ($LASTEXITCODE -ne 0) { throw 'Source files changed during qualification; the executable was not published.' }
    $distRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'dist'))
    $checkedDestination = [System.IO.Path]::GetFullPath($destination)
    $checkedArtifact = [System.IO.Path]::GetFullPath($artifact)
    $checkedRunRoot = [System.IO.Path]::GetFullPath($runRoot)
    if ($checkedDestination -ne (Join-Path $distRoot $profile) -or
        -not $checkedArtifact.StartsWith($checkedRunRoot + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The artifact publication paths are outside the verified build directories.'
    }
    New-Item -ItemType Directory -Path $distRoot -Force | Out-Null
    $previous = Join-Path $distRoot ($profile + '.previous-' + [Guid]::NewGuid().ToString('N'))
    $checkedPrevious = [System.IO.Path]::GetFullPath($previous)
    if ([System.IO.Path]::GetDirectoryName($checkedPrevious) -ne $distRoot) {
        throw 'The previous artifact archive is outside the verified distribution directory.'
    }
    if (Test-Path -LiteralPath $destination) {
        # Preserve the complete earlier artifact. Each fresh run has a private
        # staging directory, so skipped installs never inherit stale evidence.
        Move-Item -LiteralPath $destination -Destination $previous
    }
    try {
        Move-Item -LiteralPath $artifact -Destination $destination
    } catch {
        if ((Test-Path -LiteralPath $previous) -and -not (Test-Path -LiteralPath $destination)) {
            Move-Item -LiteralPath $previous -Destination $destination
        }
        throw
    }
    Write-Host "Build and isolated packaged smoke check passed: $(Join-Path $destination 'TolForge.exe')"
} finally {
    foreach ($name in $savedEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    Pop-Location
}
