$ErrorActionPreference = "Stop"

Write-Host "Installing build dependencies..."
python -m pip install --upgrade pip
python -m pip install pyinstaller

Write-Host "Building TolForge single-file executable..."
python -m PyInstaller --clean --noconfirm --windowed --onefile --name "TolForge" "Code/gui/app.py"

Write-Host "Build complete. See the 'dist' folder for the single-file executable at 'dist\TolForge.exe'."