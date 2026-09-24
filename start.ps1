$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & '.\.venv\Scripts\python.exe' main.py
} finally {
    Pop-Location
}
