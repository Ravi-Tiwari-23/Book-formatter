$ErrorActionPreference = "Stop"

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    throw "Virtual environment not found. Run .\setup.ps1 first."
}

$gtkCandidates = @(
    $env:TRUELOGGER_GTK_BIN,
    "C:\msys64-truelogger\ucrt64\bin",
    "C:\msys64\ucrt64\bin"
)
$gtkBin = $gtkCandidates | Where-Object {
    $_ -and (Test-Path (Join-Path $_ "libgobject-2.0-0.dll"))
} | Select-Object -First 1
if ($gtkBin) {
    $env:WEASYPRINT_DLL_DIRECTORIES = $gtkBin
}

& .\.venv\Scripts\python.exe -m streamlit run app.py

