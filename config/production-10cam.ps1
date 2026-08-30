$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Chưa tìm thấy môi trường .venv" }
& $Python (Join-Path $Root "run_app.py") --mode normal --device cuda:0 --max-cameras 10 --no-startup-dialog
exit $LASTEXITCODE
