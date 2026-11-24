# Build ClaudeGhost.exe (PyInstaller) and the installer (Inno Setup) on Windows.
# Run: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

python -m PyInstaller --noconfirm --clean --windowed `
  --name ClaudeGhost `
  --icon assets\icon.ico `
  --collect-all faster_whisper `
  --collect-all ctranslate2 `
  --collect-all onnxruntime `
  --collect-all tokenizers `
  --collect-all sounddevice `
  --collect-all _sounddevice_data `
  ghost.py

# Check that all dependencies made it into the bundle
$p = Start-Process -FilePath "dist\ClaudeGhost\ClaudeGhost.exe" -ArgumentList "--selftest" -Wait -PassThru
Get-Content "$env:APPDATA\ClaudeGhost\selftest.txt"
if ($p.ExitCode -ne 0) { throw "selftest failed" }

# Installer
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc installer\ClaudeGhost.iss
Write-Host "Done: dist\ClaudeGhost-Setup.exe"
