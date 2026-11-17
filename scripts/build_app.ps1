# Builds "Macro Recorder.exe" into dist\. Run it from the project folder:
#   .\scripts\build_app.ps1
# Experimental: written and syntax-checked, but not yet run on a real Windows PC.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$iconArg = @()
if (Test-Path "scripts\icon.ico") {
    $iconArg = @("--icon", "scripts\icon.ico")
}

# Newer Python installs now ship Tcl/Tk 9, whose library names PyInstaller's bundler
# does not always find on its own -- add them explicitly so the built exe doesn't
# crash on "libtcl9... not found" the moment it's opened. This was CONFIRMED necessary
# on the equivalent Mac/Linux build (it crashed without this); the exact DLL location
# on Windows is checked in a few likely spots below rather than verified on real
# Windows, so if none of them find anything, that is worth telling me about.
$pyRoot = Split-Path (python -c "import sys; print(sys.executable)")
$tclArgs = @()
foreach ($dir in @($pyRoot, (Join-Path $pyRoot "DLLs"), (Join-Path $pyRoot "Lib"))) {
    if (Test-Path $dir) {
        Get-ChildItem -Path $dir -Filter "tcl9*.dll" -ErrorAction SilentlyContinue | ForEach-Object {
            $tclArgs += @("--add-binary", "$($_.FullName);.")
        }
    }
}
if ($tclArgs.Count -eq 0) {
    Write-Host "Note: could not find Tcl/Tk 9 DLLs near $pyRoot -- if the built exe"
    Write-Host "fails to open with a 'tcl9... not found' error, that's why."
}

pyinstaller --noconfirm --onefile --windowed --name "Macro Recorder" `
    @iconArg @tclArgs --paths . --collect-all customtkinter --collect-all cv2 scripts\launch.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }

Write-Host "Done. The file is dist\Macro Recorder.exe"
Write-Host "No special permissions are needed to run it, unlike the Mac version."
Write-Host "It is not signed, so Windows SmartScreen may warn the first time it runs."
Write-Host "Click 'More info', then 'Run anyway' -- this is expected for an unsigned exe, not a bug."
