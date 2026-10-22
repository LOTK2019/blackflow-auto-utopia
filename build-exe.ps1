param([string]$MaaSourcePath)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($MaaSourcePath) {
    & '.\.venv\Scripts\python.exe' tools/stage_engine.py $MaaSourcePath
    if ($LASTEXITCODE -ne 0) { throw 'Engine staging failed' }
}
& '.\.venv\Scripts\python.exe' -m pip install 'pyinstaller==6.22.3'
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed' }
& '.\.venv\Scripts\python.exe' -m PyInstaller blackflow.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
# 发布默认配置不携带作者的安装路径或模拟器地址。
& '.\.venv\Scripts\python.exe' -c "from blackflow.config import Config; Config().save('dist/自动实托邦/config.json')"
Copy-Item -LiteralPath EXE使用说明.txt,LICENSE,README.md,验证记录.md -Destination 'dist/自动实托邦/'
Write-Host 'EXE: dist/自动实托邦/自动实托邦.exe'
