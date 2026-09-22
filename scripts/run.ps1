$skillRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $skillRoot
$env:PYTHONPATH = Join-Path $skillRoot 'scripts'
& '.\.venv\Scripts\python.exe' -X utf8 -m wecom_digest @args
exit $LASTEXITCODE
