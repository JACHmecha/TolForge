param([switch]$SkipDependencyInstall, [switch]$IncludeCad)

$ErrorActionPreference = "Stop"
$oldCadProfile = $env:TOLFORGE_BUILD_CAD
$oldQtPlatform = $env:QT_QPA_PLATFORM
Push-Location $PSScriptRoot
try {
    if (-not $SkipDependencyInstall) {
        Write-Host "Installing the declared build dependencies..."
        python -m pip install -r requirements.txt '.[build]'
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    }

    $env:QT_QPA_PLATFORM = 'offscreen'
    python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; the executable was not built." }

    if ($IncludeCad) {
        $env:TOLFORGE_BUILD_CAD = '1'
        Write-Host "Building with the current environment's CAD runtime; native artifact checks are required."
    } else {
        $env:TOLFORGE_BUILD_CAD = '0'
        Write-Host "Building the desktop executable without the optional CAD runtime."
    }
    python -m PyInstaller --clean --noconfirm TolForge.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
    $executable = Join-Path $PSScriptRoot 'dist\TolForge.exe'
    if (-not (Test-Path -LiteralPath $executable)) { throw "Executable is missing." }

    $reportPath = Join-Path $PSScriptRoot 'dist\packaged-smoke.json'
    if (Test-Path -LiteralPath $reportPath) { Remove-Item -LiteralPath $reportPath }
    $smokeArgs = @('--self-check-json', "`"$reportPath`"")
    if ($IncludeCad) { $smokeArgs += '--self-check-cad' }
    $process = Start-Process -FilePath $executable -ArgumentList $smokeArgs -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(120000)) {
        $process.Kill()
        throw "Packaged smoke check timed out."
    }
    if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
        throw "Packaged smoke check failed; see dist\packaged-smoke.json if present."
    }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'ok' -or $report.frozen -ne $true) {
        throw "Packaged smoke report was unsuccessful."
    }

    python -m pip freeze | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'dist\pip-freeze.txt')
    if ($LASTEXITCODE -ne 0) { throw "Dependency manifest generation failed." }
    Get-FileHash -LiteralPath $executable -Algorithm SHA256 | Format-List | Out-String |
        Set-Content -LiteralPath (Join-Path $PSScriptRoot 'dist\SHA256.txt')
    Write-Host "Build and packaging smoke check passed: $executable"
} finally {
    $env:TOLFORGE_BUILD_CAD = $oldCadProfile
    $env:QT_QPA_PLATFORM = $oldQtPlatform
    Pop-Location
}
