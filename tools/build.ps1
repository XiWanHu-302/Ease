$ErrorActionPreference = 'Stop'
$rootPath = Split-Path $PSScriptRoot -Parent
Push-Location -LiteralPath $rootPath
try {
    $pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
    & $pythonPath tools/collect_licenses.py
    if ($LASTEXITCODE -ne 0) { throw 'License collection failed' }
    $env:MPLBACKEND = 'Agg'
    & $pythonPath -m PyInstaller --noconfirm packaging/zuoban.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
    Copy-Item -LiteralPath (Join-Path $rootPath 'README.md') -Destination (Join-Path $rootPath 'dist\ZuoBan\README.md')
    Copy-Item -LiteralPath (Join-Path $rootPath 'THIRD_PARTY_NOTICES.md') -Destination (Join-Path $rootPath 'dist\ZuoBan\THIRD_PARTY_NOTICES.md')
    Copy-Item -LiteralPath (Join-Path $rootPath 'licenses') -Destination (Join-Path $rootPath 'dist\ZuoBan\licenses') -Recurse -Force
} finally {
    Pop-Location
}
