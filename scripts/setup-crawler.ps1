$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$corePython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$crawlerPython = Join-Path $projectRoot '.venv-crawler\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $corePython)) { throw 'Install the core .venv environment first.' }
if (-not (Test-Path -LiteralPath $crawlerPython)) {
    & $corePython -m venv (Join-Path $projectRoot '.venv-crawler')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the crawler environment.' }
}
$lockPath = Join-Path $projectRoot 'requirements-crawler.lock.txt'
$requirementsPath = Join-Path $projectRoot 'requirements-crawler.txt'
if (Test-Path -LiteralPath $lockPath) { $requirementsPath = $lockPath }
& $crawlerPython -m pip install -r $requirementsPath
if ($LASTEXITCODE -ne 0) { throw 'Crawler dependency installation failed.' }
$previousBrowserPath = $env:PLAYWRIGHT_BROWSERS_PATH
try {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot '.cache\ms-playwright'
    & $crawlerPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Browser installation failed.' }
} finally {
    $env:PLAYWRIGHT_BROWSERS_PATH = $previousBrowserPath
}
& $crawlerPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Crawler dependency check failed.' }
