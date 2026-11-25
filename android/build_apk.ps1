#requires -Version 5.1
<#
    Builds the BigSeek Android APK without Gradle.

    Requires: Android SDK (build-tools + a platform) and a JDK (Android Studio's
    bundled JBR works). Optionally installs the APK to the device via adb.

    Examples:
      powershell -ExecutionPolicy Bypass -File android\build_apk.ps1
      powershell -ExecutionPolicy Bypass -File android\build_apk.ps1 -Install -Launch
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Install,
    [switch]$Launch,
    [string]$Adb = ""
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$app = Join-Path $root "app"
$build = Join-Path $root "build"
$versionName = "1.0.4"
$versionCode = "5"

function Find-Sdk {
    foreach ($candidate in @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME,
                             (Join-Path $env:LOCALAPPDATA "Android\Sdk"))) {
        if ($candidate -and (Test-Path $candidate)) { return $candidate }
    }
    throw "Android SDK not found. Set ANDROID_SDK_ROOT."
}

function Find-Jdk {
    $candidates = @()
    if ($env:JAVA_HOME) { $candidates += $env:JAVA_HOME }
    $candidates += @(
        "C:\Program Files\Android\Android Studio\jbr",
        "C:\Program Files\Java\jdk-21",
        "C:\Program Files\Java\jdk-17"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path (Join-Path $candidate "bin\javac.exe"))) {
            return $candidate
        }
    }
    $javac = Get-Command javac -ErrorAction SilentlyContinue
    if ($javac) { return (Split-Path -Parent (Split-Path -Parent $javac.Source)) }
    throw "JDK not found (javac). Install Android Studio or a JDK."
}

$sdk = Find-Sdk
$jdk = Find-Jdk
$buildTools = Get-ChildItem (Join-Path $sdk "build-tools") -Directory |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $buildTools) { throw "No build-tools in $sdk" }
$bt = $buildTools.FullName

$platform = Get-ChildItem (Join-Path $sdk "platforms") -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName "android.jar") } |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $platform) { throw "No Android platform (android.jar) installed." }
$androidJar = Join-Path $platform.FullName "android.jar"

$aapt2 = Join-Path $bt "aapt2.exe"
$d8 = Join-Path $bt "d8.bat"
$zipalign = Join-Path $bt "zipalign.exe"
$apksigner = Join-Path $bt "apksigner.bat"
$javac = Join-Path $jdk "bin\javac.exe"
$jar = Join-Path $jdk "bin\jar.exe"
$keytool = Join-Path $jdk "bin\keytool.exe"

foreach ($tool in @($aapt2, $d8, $zipalign, $apksigner, $javac, $jar, $keytool, $androidJar)) {
    if (-not (Test-Path $tool)) { throw "Missing tool: $tool" }
}

$env:JAVA_HOME = $jdk
$env:Path = (Join-Path $jdk "bin") + ";" + $env:Path

if ($Clean -and (Test-Path $build)) { Remove-Item $build -Recurse -Force }
New-Item -ItemType Directory -Force -Path $build | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $build "gen") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $build "classes") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $build "dex") | Out-Null

Write-Host "SDK:    $sdk"
Write-Host "JDK:    $jdk"
Write-Host "BT:     $bt"
Write-Host "Jar:    $androidJar"

Write-Host ""
Write-Host "=== Resources ==="
& $aapt2 compile --dir (Join-Path $app "res") -o (Join-Path $build "res.zip")
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

& $aapt2 link `
    -o (Join-Path $build "base.apk") `
    -I $androidJar `
    -A (Join-Path $app "assets") `
    --manifest (Join-Path $app "AndroidManifest.xml") `
    --java (Join-Path $build "gen") `
    --min-sdk-version 26 `
    --target-sdk-version 34 `
    --version-code $versionCode `
    --version-name $versionName `
    (Join-Path $build "res.zip")
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

Write-Host ""
Write-Host "=== Java ==="
$sources = @()
$sources += (Get-ChildItem (Join-Path $app "java") -Recurse -Filter *.java |
    ForEach-Object { $_.FullName })
$sources += (Get-ChildItem (Join-Path $build "gen") -Recurse -Filter *.java |
    ForEach-Object { $_.FullName })
Write-Host ("Compiling {0} files" -f $sources.Count)
& $javac --release 17 -encoding UTF-8 -classpath $androidJar `
    -d (Join-Path $build "classes") $sources
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

Write-Host ""
Write-Host "=== Dex ==="
& $jar cf (Join-Path $build "classes.jar") -C (Join-Path $build "classes") .
if ($LASTEXITCODE -ne 0) { throw "jar failed" }
& $d8 --release --min-api 26 --lib $androidJar `
    --output (Join-Path $build "dex") (Join-Path $build "classes.jar")
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }

Write-Host ""
Write-Host "=== Package ==="
& python (Join-Path $root "tools\add_dex.py") `
    (Join-Path $build "base.apk") `
    (Join-Path $build "dex\classes.dex") `
    (Join-Path $build "unsigned.apk")
if ($LASTEXITCODE -ne 0) { throw "packaging failed" }

& $zipalign -f 4 (Join-Path $build "unsigned.apk") (Join-Path $build "aligned.apk")
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

$keystore = Join-Path $root "keystore\bigseek.jks"
if (-not (Test-Path $keystore)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $keystore) | Out-Null
    Write-Host "Creating signing key..."
    & $keytool -genkeypair -keystore $keystore -alias bigseek `
        -keyalg RSA -keysize 2048 -validity 10000 -storetype PKCS12 `
        -storepass bigseek -keypass bigseek `
        -dname "CN=BigSeek, O=1mpsb1, C=RU" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "keytool failed" }
}

& $apksigner sign --ks $keystore --ks-pass pass:bigseek --key-pass pass:bigseek `
    --out (Join-Path $build "BigSeek.apk") (Join-Path $build "aligned.apk")
if ($LASTEXITCODE -ne 0) { throw "apksigner failed" }

& $apksigner verify (Join-Path $build "BigSeek.apk")
if ($LASTEXITCODE -ne 0) { throw "apksigner verify failed" }

$apk = Join-Path $build "BigSeek.apk"
$sizeMb = [math]::Round((Get-Item $apk).Length / 1MB, 2)
Write-Host ""
Write-Host ("APK: {0} ({1} MB)" -f $apk, $sizeMb)

if ($Install -or $Launch) {
    $adbPath = $Adb
    if (-not $adbPath) {
        $candidates = @(
            "C:\Users\vitaliy\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
            (Join-Path $sdk "platform-tools\adb.exe"),
            $env:ADB
        )
        foreach ($candidate in $candidates) {
            if ($candidate -and (Test-Path $candidate)) { $adbPath = $candidate; break }
        }
        if (-not $adbPath) {
            $cmd = Get-Command adb -ErrorAction SilentlyContinue
            if ($cmd) { $adbPath = $cmd.Source }
        }
    }
    if (-not $adbPath) { throw "adb not found; pass -Adb <path>." }

    Write-Host "Installing via $adbPath"
    & $adbPath install -r -d $apk
    if ($LASTEXITCODE -ne 0) { throw "adb install failed" }
    if ($Launch) {
        & $adbPath shell am force-stop com.bigseek.app
        & $adbPath shell am start -n com.bigseek.app/.MainActivity | Out-Null
    }
}
