param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("A", "B", "C")]
    [string]$Config,

    [Parameter(Mandatory = $true)]
    [string]$Database,

    [Parameter(Mandatory = $true)]
    [string[]]$Cameras,

    [int]$MaxCameras = 3,
    [int]$DurationMinutes = 0
)

# scripts/run_rtsp_ab_test.ps1 - Phase 4 / Phase 4.1 A/B RTSP test harness.
#
# Chay 1 trong 3 cau hinh A/B/C (model/imgsz - xem scripts/create_ab_test_database.py::
# AB_TEST_CONFIGS, day la NGUON SU THAT DUY NHAT) tren DATABASE RIENG CUA DUNG CASE DO -
# KHONG BAO GIO dung data\parking.db (production dang song). Ca 3 cau hinh deu FP32.
#
# Script nay KHONG sua production-10cam.ps1, KHONG doi RUNTIME_PROFILES production_10cam,
# KHONG mo camera ngoai danh sach -Cameras, KHONG chay qua 3 camera cung luc.
#
# Phase 4.1: -Database PHAI la 1 trong 3 file DOC LAP do 'prepare' tao (ab_test_A.db /
# ab_test_B.db / ab_test_C.db) - KHONG BAO GIO dung 1 file .db dung chung cho ca 3 case
# (day la loi Phase 4 cu, da sua o Phase 4.1). Neu -Database duoc chi dinh khong khop
# config duoc sidecar metadata (*.meta.json) gan cho no, create_ab_test_database.py se
# tu choi voi AB_DATABASE_REUSE_FORBIDDEN - khong co unsafe override.
#
# Buoc 1 (chay 1 lan truoc ca 3 case, KHONG chay lai cho tung case):
#   python scripts\create_ab_test_database.py prepare
#   -> in ra pristine + 3 duong dan: data\runtime_ab\<timestamp>\A\ab_test_A.db (v.v.)
#
# Vi du (3 lan chay, moi lan 1 -Database RIENG - khong dung chung):
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_rtsp_ab_test.ps1 `
#       -Config A -Database .\data\runtime_ab\<timestamp>\A\ab_test_A.db `
#       -Cameras CAM01,CAM02,CAM03 -MaxCameras 3
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_rtsp_ab_test.ps1 `
#       -Config B -Database .\data\runtime_ab\<timestamp>\B\ab_test_B.db `
#       -Cameras CAM01,CAM02,CAM03 -MaxCameras 3
#   powershell -ExecutionPolicy Bypass -File .\scripts\run_rtsp_ab_test.ps1 `
#       -Config C -Database .\data\runtime_ab\<timestamp>\C\ab_test_C.db `
#       -Cameras CAM01,CAM02,CAM03 -MaxCameras 3

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$AbTool = Join-Path $Root "scripts\create_ab_test_database.py"

if (-not (Test-Path -LiteralPath $Python)) {
    Write-Host "AB_TEST_VENV_NOT_FOUND: $Python - hay chay scripts\setup-dev.ps1 truoc." -ForegroundColor Red
    exit 1
}

if ($MaxCameras -gt 3) {
    Write-Host "AB_TEST_MAX_CAMERAS_EXCEEDS_LIMIT: Phase 4 chi cho phep toi da 3 camera (yeu cau $MaxCameras)." -ForegroundColor Red
    exit 1
}
if ($Cameras.Count -ne $MaxCameras) {
    Write-Host "AB_TEST_CAMERA_COUNT_MISMATCH: -Cameras co $($Cameras.Count) ma nhung -MaxCameras=$MaxCameras. Ca 3 case A/B/C phai dung CUNG mot danh sach camera." -ForegroundColor Red
    exit 1
}

# --- 1) TU CHOI neu -Database trung voi production DB. Kiem tra bang duong dan tuyet
# doi, khong doi hoi file da ton tai (GetFullPath, khong dung Resolve-Path), va so sanh
# khong phan biet hoa/thuong vi Windows filesystem khong phan biet case. Day la lop bao
# ve DAU TIEN - truoc ca khi cham vao create_ab_test_database.py (lop bao ve THU HAI,
# xem is_production_database() trong file do).
$ProductionDbFull = [System.IO.Path]::GetFullPath((Join-Path $Root "data\parking.db"))
$DatabaseFull = [System.IO.Path]::GetFullPath($Database)
if ($DatabaseFull -ieq $ProductionDbFull) {
    Write-Host "AB_TEST_REFUSES_PRODUCTION_DB: -Database ($Database) trung voi database production ($ProductionDbFull). A/B test PHAI dung 1 database rieng cho tung case - xem: python scripts\create_ab_test_database.py prepare" -ForegroundColor Red
    exit 1
}

# --- 2) Doc model/imgsz cua config tu NGUON SU THAT DUY NHAT (create_ab_test_database.py
# AB_TEST_CONFIGS) - KHONG hardcode lai mapping A/B/C rieng trong PowerShell.
$describeOutput = & $Python $AbTool describe --config $Config 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host ($describeOutput -join "`n") -ForegroundColor Red; exit 1 }
$configMap = @{}
foreach ($line in $describeOutput) { if ($line -match "^([A-Z_]+)=(.*)$") { $configMap[$Matches[1]] = $Matches[2] } }
$Model = $configMap["MODEL"]; $ImgSz = $configMap["IMGSZ"]
if (-not $Model -or -not $ImgSz) {
    Write-Host "AB_TEST_DESCRIBE_PARSE_FAILED: khong doc duoc MODEL/IMGSZ tu create_ab_test_database.py describe" -ForegroundColor Red
    exit 1
}

# --- 3) Model file guard - khong bao gio de Ultralytics tu tai. ---
$ModelPath = Join-Path $Root "models\$Model"
if (-not (Test-Path -LiteralPath $ModelPath)) {
    Write-Host "AB_MODEL_NOT_FOUND: $ModelPath" -ForegroundColor Red
    exit 1
}

# --- 4) CUDA guard - A/B chi chay cuda:0, khong fallback CPU. Dung truoc khi dung app. ---
& $Python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "AB_CUDA_UNAVAILABLE: CUDA khong kha dung tren may nay - A/B test chi chay cuda:0, khong fallback CPU." -ForegroundColor Red
    exit 1
}
$CudaDeviceName = (& $Python -c "import torch; print(torch.cuda.get_device_name(0))").Trim()

# --- 5) DB rieng cua case nay phai da duoc tao truoc (buoc 'prepare' - tao pristine + ca
# 3 database A/B/C DOC LAP cung luc). Khong tu tao o day de tranh nham lan ve nguon du
# lieu - nguoi dung phai chu dong chay 'prepare' 1 lan truoc ca 3 case. ---
if (-not (Test-Path -LiteralPath $Database)) {
    Write-Host "AB_TEST_DATABASE_NOT_FOUND: $Database - hay chay truoc: python scripts\create_ab_test_database.py prepare" -ForegroundColor Red
    exit 1
}

# --- 6) Chon dung 3 camera + set detector_image_size TREN DATABASE RIENG CUA CASE NAY
# (khong dong den production DB - da chan o buoc 1; create_ab_test_database.py chan lai
# lan nua o buoc nay - phong thu 2 lop; va tu choi neu -Database nay da duoc 'prepare'
# gan cho 1 config KHAC - AB_DATABASE_REUSE_FORBIDDEN, khong co unsafe override). Day la
# buoc BAT BUOC vi image_size duoc doc TU CAMERA ROW
# trong DB (khong phai tu bien moi truong) - xem docstring create_ab_test_database.py.
$cameraArgs = @()
foreach ($code in $Cameras) { $cameraArgs += "--camera"; $cameraArgs += $code }
& $Python $AbTool configure --database $Database --config $Config @cameraArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# --- 7) MODEL + PRECISION qua environment variable CUA RIENG PROCESS NAY - khong ghi ra
# file, khong persist QSettings, khong sua production-10cam.ps1. Bien duoc doc boi
# app/core/config.py::Settings (PARKING_DETECTOR_MODEL/PARKING_DETECTOR_HALF), day la
# ten bien MOI TRUONG THUC TE cua project - khong phai ten tu dat.
$env:PARKING_DETECTOR_MODEL = $ModelPath
$env:PARKING_DETECTOR_HALF = "0"   # Phase 4: production_10cam mac dinh da FP32, dong
                                    # nay chi de dam bao ro rang/khong phu thuoc default.

$StartTime = Get-Date
Write-Host "=== A/B TEST CASE $Config ===" -ForegroundColor Cyan
Write-Host "START_TIME: $($StartTime.ToString('o'))"
Write-Host "CONFIG: $Config"
Write-Host "MODEL: $Model"
Write-Host "IMGSZ: $ImgSz"
Write-Host "PRECISION: FP32"
Write-Host "CAMERA_COUNT: $($Cameras.Count)"
Write-Host "CAMERAS: $($Cameras -join ',')"
Write-Host "DEVICE: cuda:0"
Write-Host "CUDA_DEVICE: $CudaDeviceName"
Write-Host "DB_TEST_PATH: $Database"
$LogDir = Join-Path $Root "logs\production"
Write-Host "LOG_DIR: $LogDir"
Write-Host ""

# --- 8) Chay app that su. --mode normal (database_mode=PRODUCTION) dung dung cot
# cameras.enabled de chon camera hoat dong - buoc 6 da dam bao dung 3 camera trong
# -Cameras duoc bat, moi camera khac bi tat, nen khong the vuot qua $MaxCameras camera
# du DB copy con bao nhieu camera enabled khac tu production.
$AppArgs = @("--mode","normal","--device","cuda:0","--max-cameras",$MaxCameras,"--database",$Database,"--no-startup-dialog")
if ($DurationMinutes -gt 0) {
    $proc = Start-Process -FilePath $Python -ArgumentList (@((Join-Path $Root "run_app.py")) + $AppArgs) -PassThru -NoNewWindow -WorkingDirectory $Root
    Write-Host "PROCESS_STATUS: STARTED pid=$($proc.Id) - se tu dung sau $DurationMinutes phut"
    $exited = Wait-Process -Id $proc.Id -Timeout ($DurationMinutes * 60) -ErrorAction SilentlyContinue
    if (-not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force
        Write-Host "PROCESS_STATUS: STOPPED_BY_DURATION"
    } else {
        Write-Host "PROCESS_STATUS: EXITED_BEFORE_DURATION exit_code=$($proc.ExitCode)"
    }
} else {
    & $Python (Join-Path $Root "run_app.py") @AppArgs
    Write-Host "PROCESS_STATUS: EXITED exit_code=$LASTEXITCODE"
}

$EndTime = Get-Date
Write-Host ""
Write-Host "END_TIME: $($EndTime.ToString('o'))"
Write-Host "DURATION_SECONDS: $([int]($EndTime - $StartTime).TotalSeconds)"
Write-Host "=== A/B TEST CASE $Config KET THUC - dien ket qua vao reports\templates\rtsp_ab_test_template.md ===" -ForegroundColor Cyan
exit $LASTEXITCODE
