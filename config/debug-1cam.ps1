param([Parameter(Mandatory=$true)][string]$CameraCode,[string]$Device="auto")
$Root=Split-Path -Parent $PSScriptRoot
$Python=Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Chưa tìm thấy môi trường .venv" }
& $Python (Join-Path $Root "run_app.py") --mode debug --max-cameras 1 --camera $CameraCode --device $Device
exit $LASTEXITCODE
