#requires -Version 5.1
<#
    Builds the complete Windows release into .\release:

      * dist\BigSeek Desktop\BigSeek Desktop.exe  (PyInstaller, onedir)
      * release\BigSeek-Desktop-<ver>-portable.zip
      * release\BigSeek-Desktop-<ver>-setup.exe    (Inno Setup, optional)
      * release\SHA256SUMS.txt

    Examples:
      powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
      powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -Version 1.2.0
      powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$SkipExe,
    [switch]$SkipPortable,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Find-Python {
    foreach ($name in @("py", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"
    if (Test-Path $fallback) { return $fallback }
    throw "Python 3.10+ not found in PATH."
}

function Find-Iscc {
    $candidates = @()
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        foreach ($edition in @("Inno Setup 7", "Inno Setup 6")) {
            $candidates += (Join-Path $base "$edition\ISCC.exe")
        }
    }
    foreach ($path in $candidates) {
        if (Test-Path $path) { return $path }
    }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

if (-not $Version) {
    $versionFile = Join-Path $root "version.txt"
    if (Test-Path $versionFile) {
        $Version = (Get-Content $versionFile -Raw).Trim()
    }
}
if (-not $Version) { $Version = "1.2.0" }

$dist = Join-Path $root "dist\BigSeek Desktop"
$exe = Join-Path $dist "BigSeek Desktop.exe"
$release = Join-Path $root "release"
New-Item -ItemType Directory -Force -Path $release | Out-Null

Write-Host "BigSeek Desktop $Version" -ForegroundColor White
Write-Host "Project: $root"

# --------------------------------------------------------------------- exe
if (-not $SkipExe) {
    Write-Step "Building executable with PyInstaller"

    Get-Process -Name "BigSeek Desktop" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2

    $python = Find-Python
    Write-Host "Python: $python"

    & $python -m pip install --upgrade --quiet pip
    & $python -m pip install --quiet -r (Join-Path $root "requirements.txt")
    & $python -m pip install --upgrade --quiet "pyinstaller>=6.10"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install build dependencies." }

    # version.txt travels inside the exe so the About box can show the version.
    $versionData = (Join-Path $root "version.txt") + ";."

    & $python -m PyInstaller --noconfirm --clean --windowed `
        --name "BigSeek Desktop" `
        --icon (Join-Path $root "assets\app.ico") `
        --add-data "$versionData" `
        --workpath (Join-Path $root "build\work") `
        --specpath (Join-Path $root "build") `
        --distpath (Join-Path $root "dist") `
        (Join-Path $root "main.py")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }
}

if (-not (Test-Path $exe)) {
    throw "Missing $exe. Run the executable build first."
}

# ---------------------------------------------------------------- portable
$portable = Join-Path $release "BigSeek-Desktop-$Version-portable.zip"
if (-not $SkipPortable) {
    Write-Step "Packing portable ZIP"
    if (Test-Path $portable) { Remove-Item $portable -Force }

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $dist,
        $portable,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true
    )
    $sizeMb = [math]::Round((Get-Item $portable).Length / 1MB, 1)
    Write-Host "Created $portable ($sizeMb MB)"
}

# --------------------------------------------------------------- installer
if (-not $SkipInstaller) {
    Write-Step "Building installer with Inno Setup"
    $iscc = Find-Iscc
    if (-not $iscc) {
        Write-Warning "Inno Setup not found - installer skipped."
        Write-Warning "Install it from https://jrsoftware.org/isdl.php and run this script again."
    }
    else {
        Write-Host "ISCC: $iscc"
        & $iscc "/DAppVersion=$Version" (Join-Path $root "installer\BigSeekDesktop.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
    }
}

# --------------------------------------------------------------- checksums
Write-Step "Writing SHA256SUMS.txt"
$sums = Join-Path $release "SHA256SUMS.txt"
$lines = @()
Get-ChildItem -Path $release -File |
    Where-Object { $_.Extension -in @(".exe", ".zip") } |
    Sort-Object Name |
    ForEach-Object {
        $hash = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash.ToLower()
        $lines += "$hash  $($_.Name)"
    }
$lines | Set-Content -Path $sums -Encoding ASCII
$lines | ForEach-Object { Write-Host "  $_" }

Write-Step "Done"
Get-ChildItem -Path $release -File |
    Sort-Object Name |
    ForEach-Object { Write-Host ("  {0,-46} {1,8:N1} MB" -f $_.Name, ($_.Length / 1MB)) }
