$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath .\.venv\Scripts\python.exe)) {
        throw "Bookloom environment not found. Run .\setup.ps1 first."
    }

    $gtkCandidates = @(
        $env:BOOKLOOM_GTK_BIN,
        $env:TRUELOGGER_GTK_BIN,
        "C:\msys64-truelogger\ucrt64\bin",
        "C:\msys64\ucrt64\bin"
    )
    $gtkBin = $gtkCandidates | Where-Object {
        $_ -and (Test-Path -LiteralPath (Join-Path $_ "libgobject-2.0-0.dll"))
    } | Select-Object -First 1
    if ($gtkBin) {
        $env:WEASYPRINT_DLL_DIRECTORIES = $gtkBin
    }

    & .\.venv\Scripts\python.exe -m streamlit run app.py
}
finally {
    Pop-Location
}

