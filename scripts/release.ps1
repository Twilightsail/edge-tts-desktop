<#
.SYNOPSIS
  一键构建可发给别人的发布包：检查 → 测试 → 打包 → 许可声明 → 安装包 → 端到端验证 → 汇总到 release\vX.Y.Z\

.EXAMPLE
  .\scripts\release.ps1 -Contact "https://github.com/用户/仓库/issues" -License "MIT（见仓库根目录 LICENSE 文件）" -Source "https://github.com/用户/仓库"
                                                        # 正式发布：这三项会写进《第三方许可声明》，缺一项脚本就拒绝
  .\scripts\release.ps1 -AllowPlaceholder -SkipE2E       # 本地试跑

  签名：设置环境变量 EDGE_TTS_SIGN_THUMBPRINT=<证书指纹> 后运行即可（证书需已装入当前用户的证书库）。
#>
param(
    [string]$Contact = "",
    [string]$License = "",
    [string]$Source = "",
    [switch]$AllowPlaceholder,
    [switch]$SkipE2E
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
$started = Get-Date

function Step([string]$name, [scriptblock]$body) {
    Write-Host "`n━━ $name" -ForegroundColor Cyan
    & $body
    if ($LASTEXITCODE -ne 0) { throw "步骤失败：$name（退出码 $LASTEXITCODE）" }
}

if (-not (Test-Path $python)) { throw "找不到后端虚拟环境。请先在 backend 目录执行：uv sync --frozen --extra dev" }

Step "1/9 版本号一致性" { node scripts/version.mjs }
$version = (Get-Content desktop\src-tauri\tauri.conf.json -Raw | ConvertFrom-Json).version

Step "2/9 后端：代码检查与测试" {
    Push-Location backend
    try {
        & .\.venv\Scripts\ruff.exe check src tests scripts run_backend.py
        if ($LASTEXITCODE -ne 0) { return }
        & .\.venv\Scripts\ruff.exe format --check src tests
        if ($LASTEXITCODE -ne 0) { return }
        & .\.venv\Scripts\pytest.exe -q
    } finally { Pop-Location }
}

Step "3/9 后端：打包并做冒烟测试" { & (Join-Path $root "backend\build.ps1") }

Step "4/9 许可检查：后端程序中不得包含 GPL 的 mutagen" {
    $toc = Get-Content backend\build\edge-tts-backend\PYZ-00.toc -Raw
    if ($toc -match "mutagen") { Write-Error "打包产物里仍含 mutagen（GPL-2.0+）。"; $global:LASTEXITCODE = 1 } else { Write-Host "通过：打包产物不含 mutagen"; $global:LASTEXITCODE = 0 }
}

Step "5/9 第三方许可声明" {
    $notices = @("scripts\gen_notices.py")
    if ($Contact) { $notices += @("--contact", $Contact) }
    if ($License) { $notices += @("--license", $License) }
    if ($Source) { $notices += @("--source", $Source) }
    & $python @notices
    if ($LASTEXITCODE -ne 0) { return }
    $text = Get-Content frontend\public\third-party-notices.txt -Raw -Encoding UTF8
    if ($text.Contains("[请发布者填写]") -and -not $AllowPlaceholder) {
        Write-Error "许可声明里的联系方式还是占位符。GPL/LGPL 要求提供获取源码的途径，请用 -Contact 指定（或本地试跑时加 -AllowPlaceholder）。"
        $global:LASTEXITCODE = 1
    } else { $global:LASTEXITCODE = 0 }
}

Step "6/9 前端：类型检查与单元测试" {
    Push-Location frontend
    try {
        npx tsc --noEmit
        if ($LASTEXITCODE -ne 0) { return }
        npx vitest run
    } finally { Pop-Location }
}

Step "7/9 桌面应用与安装包" {
    Push-Location desktop
    try {
        node scripts/prepare-backend.mjs
        if ($LASTEXITCODE -ne 0) { return }
        $buildArgs = @("tauri", "build")
        if ($env:EDGE_TTS_SIGN_THUMBPRINT) {
            $signConfig = Join-Path $env:TEMP "edge-tts-sign.conf.json"
            @{ bundle = @{ windows = @{ certificateThumbprint = $env:EDGE_TTS_SIGN_THUMBPRINT; digestAlgorithm = "sha256"; timestampUrl = "http://timestamp.digicert.com" } } } | ConvertTo-Json -Depth 5 | Set-Content $signConfig -Encoding UTF8
            $buildArgs += @("--config", $signConfig)
            Write-Host "将使用证书 $($env:EDGE_TTS_SIGN_THUMBPRINT) 签名"
        } else {
            Write-Host "未设置 EDGE_TTS_SIGN_THUMBPRINT：安装包将不签名（Windows 会弹出 SmartScreen 警告）" -ForegroundColor Yellow
        }
        npx @buildArgs
    } finally { Pop-Location }
}

if ($SkipE2E) {
    Write-Host "`n━━ 8/9 端到端测试：已跳过（-SkipE2E）" -ForegroundColor Yellow
} else {
    Step "8/9 端到端冒烟测试" { Push-Location desktop; try { npm run e2e } finally { Pop-Location } }
}

Step "9/9 汇总发布物" {
    $installer = Get-ChildItem "desktop\src-tauri\target\release\bundle\nsis\*_${version}_x64-setup.exe" | Select-Object -First 1
    if (-not $installer) { throw "找不到版本 $version 的安装包" }
    $out = Join-Path $root "release\v$version"
    New-Item -ItemType Directory -Force $out | Out-Null
    Copy-Item $installer.FullName $out -Force
    Copy-Item frontend\public\third-party-notices.txt (Join-Path $out "第三方许可声明.txt") -Force
    Copy-Item docs\用户指南.md $out -Force
    $hash = (Get-FileHash (Join-Path $out $installer.Name) -Algorithm SHA256).Hash.ToLower()
    "$hash  $($installer.Name)" | Set-Content (Join-Path $out "SHA256SUMS.txt") -Encoding UTF8
    $signature = Get-AuthenticodeSignature (Join-Path $out $installer.Name)
    Write-Host ("安装包：{0}（{1:N1} MB）" -f $installer.Name, ($installer.Length / 1MB))
    Write-Host "SHA256：$hash"
    Write-Host "签名状态：$($signature.Status)$(if ($signature.SignerCertificate) { '，签发给 ' + $signature.SignerCertificate.Subject })"
    Write-Host "发布目录：$out"
    $global:LASTEXITCODE = 0
}

Write-Host ("`n✓ 全部完成，用时 {0:N1} 分钟" -f ((Get-Date) - $started).TotalMinutes) -ForegroundColor Green
