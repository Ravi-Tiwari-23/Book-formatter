$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.11 or newer first."
}

py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev,opencv]"

Write-Host "Setup complete. Run .\run.ps1"
Write-Host "For scanned PDFs, install Tesseract OCR 5 and the hin + eng language packs."

