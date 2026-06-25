# Downloads the official rtk Windows binary into tokonomics/bin/.
# rtk is licensed Apache-2.0 (https://github.com/rtk-ai/rtk).
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $root "tokonomics\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

Write-Host "Resolving latest rtk release..."
$rel = Invoke-RestMethod -Uri "https://api.github.com/repos/rtk-ai/rtk/releases/latest" -Headers @{ "User-Agent" = "tokonomics" }
$asset = $rel.assets | Where-Object { $_.name -eq "rtk-x86_64-pc-windows-msvc.zip" } | Select-Object -First 1
if (-not $asset) { throw "Windows asset not found in rtk release $($rel.tag_name)" }

$zip = Join-Path $env:TEMP "rtk-win.zip"
Write-Host "Downloading $($asset.name) ($($rel.tag_name))..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
Expand-Archive -Path $zip -DestinationPath $binDir -Force
Remove-Item $zip -Force

$exe = Join-Path $binDir "rtk.exe"
if (Test-Path $exe) {
  Write-Host "rtk installed at $exe"
  & $exe --version
} else {
  throw "rtk.exe not found after extraction"
}
