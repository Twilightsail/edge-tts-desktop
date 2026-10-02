param(
    [int]$Port = 0,
    [string]$DataDir = ""
)
$ErrorActionPreference = "Stop"
$backendPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $backendPython)) {
    throw 'Run uv sync --extra dev in the backend directory first.'
}
$backendArgs = @('-m', 'edge_tts_backend', '--port', "$Port")
if ($DataDir) {
    $backendArgs += @('--data-dir', $DataDir)
}
& $backendPython @backendArgs
exit $LASTEXITCODE
