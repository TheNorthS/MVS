param([string]$Package)
$ErrorActionPreference = 'Stop'
$releaseDir = Split-Path -Parent $PSScriptRoot
if (-not $Package) {
    $wheel = Get-ChildItem -Path "$releaseDir/*.whl", "$releaseDir/dist/*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $wheel) { throw '未找到发布wheel，请用 -Package 指定文件路径。' }
    $Package = $wheel.FullName
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $installer = Join-Path ([IO.Path]::GetTempPath()) ('mvs-uv-' + [Guid]::NewGuid().ToString('N') + '.ps1')
    try {
        Invoke-WebRequest -Uri 'https://astral.sh/uv/0.13.8/install.ps1' -OutFile $installer
        & $installer
    } finally { Remove-Item -LiteralPath $installer -ErrorAction SilentlyContinue }
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
& uv tool install --python 3.12 --force "${Package}[console]"
if ($LASTEXITCODE -ne 0) { throw '安装失败' }
$binDir = & uv tool dir --bin
$mvsExe = Join-Path $binDir 'mvs.exe'
& $mvsExe init
if ($LASTEXITCODE -ne 0) { throw '初始化失败' }
Write-Host "安装完成。运行 $mvsExe token show 查看令牌，然后运行 $mvsExe serve --open。"
