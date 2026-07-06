$ErrorActionPreference = "Stop"

Write-Host "Installing build dependencies..."
python -m pip install --upgrade pip
python -m pip install pyinstaller

Write-Host "Building TolForge executable..."
python -m PyInstaller --clean --noconfirm --windowed --name "TolForge" "Code/gui/app.py"

Write-Host "Build complete. See the 'dist\TolForge' folder for the application."