param([Parameter(Mandatory=$true)][string]$CarCameraCode,[Parameter(Mandatory=$true)][string]$MotorcycleCameraCode,[string]$Device="auto")
$Root=Split-Path -Parent $PSScriptRoot
& (Join-Path $Root ".venv\Scripts\python.exe") (Join-Path $Root "run_app.py") --mode debug --max-cameras 2 --camera $CarCameraCode --camera $MotorcycleCameraCode --device $Device
exit $LASTEXITCODE
