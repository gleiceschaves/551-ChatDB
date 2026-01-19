# Cross-platform setup script for chatdb (PowerShell/Windows)

$ErrorActionPreference = "Stop"

Write-Host "Setting up chatdb..."

# Create virtual environment if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Upgrade pip
pip install --upgrade pip

# Install requirements
Write-Host "Installing dependencies..."
pip install -r requirements.txt

Write-Host "Setup complete!"
