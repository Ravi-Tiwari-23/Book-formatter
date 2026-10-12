$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python launcher 'py' was not found. Install Python 3.11 or newer first."
    }

    & py -3 -c "import sys; assert sys.version_info >= (3, 11), 'Bookloom requires Python 3.11 or newer'"
    if (-not (Test-Path -LiteralPath .\.venv\Scripts\python.exe)) {
        & py -3 -m venv .venv
    }
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
    & .\.venv\Scripts\python.exe -m pip install -e ".[dev,opencv]"
    & .\.venv\Scripts\python.exe -c "import bookloom, streamlit; print('Bookloom Python environment verified.')"

    Write-Host "Setup complete. Run .\run.ps1"
    Write-Host "For scanned PDFs, install Tesseract OCR 5 with the hin and eng language packs."
}
finally {
    Pop-Location
}

