$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先在项目根目录创建.venv并安装requirements.txt。' }
& $pythonPath (Join-Path $PSScriptRoot 'brief.py') @args
exit $LASTEXITCODE
