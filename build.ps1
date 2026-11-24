# Build ClaudeGhost.exe (PyInstaller) and the installer (Inno Setup) on Windows.
# Run: powershell -ExecutionPolicy Bypass -File build.ps1
param([string]$Version = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Version: from -Version, else from __version__ in ghost.py
if ($Version) {
  $Version = $Version.TrimStart("v", "V")
  (Get-Content ghost.py -Raw -Encoding UTF8) -replace '__version__ = "[^"]*"', "__version__ = `"$Version`"" |
    Set-Content ghost.py -Encoding UTF8 -NoNewline
} else {
  $Version = ([regex]::Match((Get-Content ghost.py -Raw -Encoding UTF8), '__version__ = "([^"]*)"')).Groups[1].Value
}
Write-Host "Building version $Version"

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
if (-not ((Get-Content "$env:APPDATA\ClaudeGhost\selftest.txt") -match [regex]::Escape($Version))) { throw "version mismatch" }

# Installer
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
& $iscc "/DAppVersion=$Version" installer\ClaudeGhost.iss
Write-Host "Done: dist\ClaudeGhost-Setup.exe"
