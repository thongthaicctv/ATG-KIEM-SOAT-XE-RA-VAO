# Phase 4.7B - HOTFIX RTSP CAPTURE STABILITY (muc M).
# Wrapper PowerShell chay scripts\diagnose_rtsp_capture_phase_4_7b.py bang Python
# trong .venv cua du an. Script Python ben trong la CHI-DOC (read-only): khong ghi
# database, khong doi cau hinh camera/model/polygon/timer.
#
# KHONG hardcode RTSP URL/credential trong file nay. Truyen URL qua tham so -RtspUrl
# hoac thiet lap truoc bien moi truong ATG_DIAG_RTSP_URL.
#
# Vi du:
#   .\scripts\diagnose-rtsp-capture.ps1 -RtspUrl "rtsp://<user>:<pass>@<ip>:554/<path>"
#
# Hoac:
#   $env:ATG_DIAG_RTSP_URL = "rtsp://<user>:<pass>@<ip>:554/<path>"
#   .\scripts\diagnose-rtsp-capture.ps1

param(
    [string]$RtspUrl = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Set-Location -LiteralPath $ProjectRoot

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "FAIL: Chua co .venv. Chay scripts\setup-dev.ps1 truoc." -ForegroundColor Red
    exit 1
}

if ($RtspUrl -ne "") {
    $env:ATG_DIAG_RTSP_URL = $RtspUrl
}

if (-not $env:ATG_DIAG_RTSP_URL) {
    Write-Host "FAIL: Chua co RTSP URL. Truyen -RtspUrl hoac thiet lap `$env:ATG_DIAG_RTSP_URL truoc khi chay." -ForegroundColor Red
    exit 2
}

Write-Host "Dang chay chan doan RTSP capture (10 phut, xem tien do moi 10s)..." -ForegroundColor Yellow
& $Python (Join-Path $ProjectRoot "scripts\diagnose_rtsp_capture_phase_4_7b.py")
exit $LASTEXITCODE
