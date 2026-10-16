# setup.ps1 — whiteboard-explainer skill 一键安装（Windows PowerShell）
#
# 步骤：探测 Python → 建 .venv → ensurepip → 装 pip 包（含引擎+模型）→ 探测 ffmpeg
[CmdletBinding()]
param(
    [switch]$SkipSelfTest
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Resolve-Path (Join-Path $ScriptDir '..')
$VenvDir   = Join-Path $SkillRoot '.venv'

function Write-Section([string]$msg) {
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor DarkGray
    Write-Host $msg
}

# 1) 探测 Python
Write-Section "whiteboard-explainer setup"
Write-Host "  skill root : $SkillRoot"
Write-Host "  venv       : $VenvDir"

$py = $null
foreach ($cand in @('py', 'python', 'python3', 'python312', 'python311', 'python310')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        $ver = & $cmd.Source -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -and [version]$ver -ge [version]'3.10') {
            $py = $cmd.Source
            break
        }
    }
}
if (-not $py) {
    Write-Host "❌ 未找到 Python 3.10+（请装 https://www.python.org/downloads/ ，勾选 Add to PATH）" -ForegroundColor Red
    exit 1
}
Write-Host "✓ python : $(& $py -V 2>&1 | Select-Object -First 1)"

# 2) 建 venv
if (-not (Test-Path $VenvDir)) {
    Write-Host "→ 建 venv .venv"
    & $py -m venv $VenvDir
}
$venvPy = Join-Path $VenvDir 'Scripts\python.exe'
& $venvPy -m ensurepip --default-pip *> $null
& $venvPy -m pip install --upgrade --disable-pip-version-check pip *> $null
Write-Host "✓ venv ready"

# 3) 装 requirements.txt（含 whiteboard-animator==0.1.1，模型随 pip 从 PyPI 下载 ~83MB）
Write-Host "→ 装 pip 包（首次会从 PyPI 下载白板引擎 + CRAFT 模型，约 83MB）"
& $venvPy -m pip install --disable-pip-version-check -r (Join-Path $SkillRoot 'requirements.txt')

# 4) 验证引擎 + CRAFT 模型随包安装到位
& $venvPy -c @'
import whiteboard_animator
from pathlib import Path
pkg = Path(whiteboard_animator.__file__).parent
model = pkg / "models" / "craft.onnx"
if model.exists():
    print(f"✓ whiteboard_animator  +  CRAFT 模型 {model.stat().st_size/1e6:.0f}MB")
else:
    print("⚠️  CRAFT 模型未随包安装（请确认 whiteboard-animator==0.1.1）")
    raise SystemExit(1)
'@
if ($LASTEXITCODE -ne 0) { exit 1 }

# 5) ffmpeg
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) {
    Write-Host "✓ ffmpeg : $(& ffmpeg -version 2>&1 | Select-Object -First 1)"
} else {
    Write-Host "⚠️  ffmpeg 未在 PATH" -ForegroundColor Yellow
    Write-Host "   推荐安装：winget install Gyan.FFmpeg  或  choco install ffmpeg" -ForegroundColor Yellow
}

# 6) 字体探测
$fontFound = $false
foreach ($cand in @(
    'C:\Windows\Fonts\msyh.ttc',
    'C:\Windows\Fonts\simhei.ttf',
    'C:\Windows\Fonts\msyhbd.ttc'
)) {
    if (Test-Path $cand) { Write-Host "✓ 中文字体: $cand"; $fontFound = $true; break }
}
if (-not $fontFound) {
    Write-Host "⚠️  未探测到系统中文字体；PIL 文字层会失败。请装任意中文黑体并放进 C:\Windows\Fonts\" -ForegroundColor Yellow
}

# 7) 自检
if (-not $SkipSelfTest) {
    Write-Host ""
    Write-Host "→ 跑 self_test.py …"
    try {
        & $venvPy (Join-Path $SkillRoot 'scripts\self_test.py') --quick
        Write-Host ""
        Write-Host "✅ 安装完成，可用：" -ForegroundColor Green
        Write-Host "   .venv\Scripts\Activate.ps1"
        Write-Host "   python scripts\build_narration.py plan.build.json"
        Write-Host "   python scripts\render_explainer.py plan.json --out out\<name>.mp4"
    } catch {
        Write-Host "⚠️  自检未全通过，但 skill 已就绪。先排查上方警告。" -ForegroundColor Yellow
    }
}
