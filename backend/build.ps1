$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    & uv sync --frozen --extra dev
    if ($LASTEXITCODE -ne 0) { throw 'Dependency sync failed.' }
    & .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --name edge-tts-backend --paths src --collect-all edge_tts --collect-all imageio_ffmpeg --exclude-module mutagen run_backend.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
    & .\.venv\Scripts\python.exe scripts\smoke_process.py --executable dist\edge-tts-backend.exe
    if ($LASTEXITCODE -ne 0) { throw 'Frozen backend smoke test failed.' }
} finally {
    Pop-Location
}
