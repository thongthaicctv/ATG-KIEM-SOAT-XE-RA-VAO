$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$CheckScript = Join-Path $ProjectRoot "scripts\environment_check.py"
$env:PARKING_RUNTIME_PROFILE = if ($env:PARKING_RUNTIME_PROFILE) { $env:PARKING_RUNTIME_PROFILE } else { "debug_1cam" }
if ($env:PARKING_RUNTIME_PROFILE -eq "debug_1cam") {
    $env:PARKING_DETECTOR_DEVICE = "cpu"; $env:PARKING_DETECTOR_HALF = "0"; $env:PARKING_MAX_CAMERAS = "1"
}
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { Write-Host "ENVIRONMENT CHECK: FAIL`nChưa tìm thấy môi trường .venv." -ForegroundColor Red; exit 1 }
Set-Location -LiteralPath $ProjectRoot
& $VenvPython $CheckScript
exit $LASTEXITCODE
