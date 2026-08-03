$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Set-Location -LiteralPath $ProjectRoot

function Find-Python310 {
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3.10 -c "import sys; print(sys.executable)" 2>$null; if ($LASTEXITCODE -eq 0) { return (& py -3.10 -c "import sys; print(sys.executable)").Trim() } }
    if (Test-Path -LiteralPath "C:\Python310\python.exe") { return "C:\Python310\python.exe" }
    if (Get-Command python -ErrorAction SilentlyContinue) { $p = (& python -c "import sys; print(sys.executable if sys.version_info[:2] == (3,10) else '')").Trim(); if ($p) { return $p } }
    return $null
}

$Python310 = Find-Python310
if (-not $Python310) { Write-Host "FAIL: Không tìm thấy Python 3.10.x." -ForegroundColor Red; exit 1 }
$Version = (& $Python310 -c "import platform; print(platform.python_version())").Trim()
if (-not $Version.StartsWith("3.10.")) { Write-Host "FAIL: Cần Python 3.10.x, hiện tại $Version" -ForegroundColor Red; exit 1 }
if (-not (Test-Path -LiteralPath $VenvPython)) { & $Python310 -m venv (Join-Path $ProjectRoot ".venv"); if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -c "import torch; print('PyTorch:', torch.__version__); print('CUDA available:', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: Chưa có PyTorch. Hãy cài bản CPU phù hợp vào .venv rồi chạy lại; script không tự đoán CUDA wheel." -ForegroundColor Red; exit 1 }
& $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VenvPython -c "import PySide6,cv2,sqlalchemy,numpy,torch,ultralytics,pytest,pytestqt; print('PASS: Runtime, AI và test dependencies')"
exit $LASTEXITCODE
