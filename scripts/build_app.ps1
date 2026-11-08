# Builds "Macro Recorder.exe" into dist\. Run it from the project folder:
#   .\scripts\build_app.ps1
# Experimental: written and syntax-checked, but not yet run on a real Windows PC.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

pyinstaller --noconfirm --onefile --windowed --name "Macro Recorder" `
    --paths . --collect-all customtkinter --collect-all cv2 scripts\launch.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

Write-Host "Done. The file is dist\Macro Recorder.exe"
Write-Host "No special permissions are needed to run it, unlike the Mac version."
Write-Host "It is not signed, so Windows SmartScreen may warn the first time it runs."
Write-Host "Click 'More info', then 'Run anyway' -- this is expected for an unsigned exe, not a bug."
