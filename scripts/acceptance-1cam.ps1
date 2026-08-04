$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
Set-Location -LiteralPath $ProjectRoot
if (-not (Test-Path -LiteralPath $Python)) { Write-Host "FAIL: Chưa có .venv. Chạy scripts\setup-dev.ps1 trước." -ForegroundColor Red; exit 1 }
& powershell -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\check-environment.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -c "from app.database.migrations import init_database; init_database(); print('Migration: PASS')"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -c "from sqlalchemy import text; from app.database.session import engine; print('Duration repair preview:', engine.connect().execute(text(\"SELECT count(*) FROM parking_sessions WHERE status='COMPLETED' AND parked_at IS NOT NULL AND left_at IS NOT NULL AND (parking_duration_seconds IS NULL OR parking_duration_seconds=0)\")).scalar_one(), 'record(s)')"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Kiểm tra tự động: PASS. Đang mở profile debug một camera; script không xóa/reset database." -ForegroundColor Green
& powershell -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "config\debug-1cam.ps1")
exit $LASTEXITCODE
