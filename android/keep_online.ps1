# Re-enables Wi-Fi if the phone lost the saved TP-Link_FE48_repeater network.
# The network is already saved in Android, so toggling Wi-Fi reconnects it.
param(
    [string]$Adb = "C:\Users\vitaliy\Downloads\platform-tools-latest-windows\platform-tools\adb.exe"
)

if (-not (Test-Path $Adb)) {
    $Adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
}
if (-not $Adb) {
    Write-Error "adb not found; pass -Adb <path>"
    exit 1
}

$devices = & $Adb devices
if ($devices -notmatch "device$") {
    Write-Error "No Android device connected via adb."
    exit 1
}

$status = (& $Adb shell cmd wifi status 2>$null) -join "`n"
if ($status -match 'connected to "([^"]+)"') {
    Write-Host "Phone is online: $($Matches[1])"
    exit 0
}

Write-Host "Phone is offline - toggling Wi-Fi to reconnect..."
& $Adb shell svc wifi disable | Out-Null
Start-Sleep -Seconds 2
& $Adb shell svc wifi enable | Out-Null
Start-Sleep -Seconds 10

$status = (& $Adb shell cmd wifi status 2>$null) -join "`n"
if ($status -match 'connected to "([^"]+)"') {
    Write-Host "Reconnected: $($Matches[1])"
    exit 0
}
Write-Warning "Still offline. Connect the phone to TP-Link_FE48_repeater manually once."
exit 1
