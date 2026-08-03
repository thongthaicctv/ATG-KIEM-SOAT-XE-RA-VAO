$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $ProjectRoot "run_app.py"
$ModelPath = Join-Path $ProjectRoot "models\yolo11n.pt"

function Stop-WithMessage([string]$Message, [int]$Code = 1) {
    Write-Host $Message -ForegroundColor Red
    if ($Host.Name -eq "ConsoleHost" -and $env:TERM_PROGRAM -ne "vscode" -and $null -eq $env:WT_SESSION) { Read-Host "Nhấn Enter để đóng cửa sổ" }
    exit $Code
}

if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) { Stop-WithMessage "Không tìm thấy project root: $ProjectRoot" }
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) { Stop-WithMessage "Chưa tìm thấy môi trường .venv.`nHãy chạy:`npowershell -ExecutionPolicy Bypass -File .\scripts\setup-dev.ps1" }
if (-not (Test-Path -LiteralPath $EntryPoint -PathType Leaf)) { Stop-WithMessage "Không tìm thấy entry point: $EntryPoint" }
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) { Stop-WithMessage "DETECTOR_MODEL_NOT_FOUND: $ModelPath" }
foreach ($Folder in @("data", "logs", "snapshots")) {
    $Path = Join-Path $ProjectRoot $Folder; New-Item -ItemType Directory -Force -Path $Path | Out-Null
    try { $Probe = Join-Path $Path ".write-test.tmp"; [IO.File]::WriteAllText($Probe, "ok"); Remove-Item -LiteralPath $Probe -Force } catch { Stop-WithMessage "Không thể ghi thư mục: $Path" }
}
$env:PARKING_RUNTIME_PROFILE = "debug_1cam"
$env:PARKING_DETECTOR_MODEL = $ModelPath
$env:PARKING_DETECTOR_DEVICE = "cpu"
$env:PARKING_DETECTOR_HALF = "0"
$env:PARKING_MAX_CAMERAS = "1"
Set-Location -LiteralPath $ProjectRoot
& $VenvPython $EntryPoint
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) { Stop-WithMessage "Ứng dụng kết thúc với exit code $ExitCode" $ExitCode }
exit 0
