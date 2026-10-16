#!/usr/bin/env bash
# setup.sh — whiteboard-explainer skill 一键安装（macOS / Linux / Git Bash）
#
# 步骤：探测 Python → 建 .venv → ensurepip → 装 pip 包（含引擎+模型）→ 探测 ffmpeg
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$SKILL_ROOT/.venv"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "whiteboard-explainer setup"
echo "  skill root : $SKILL_ROOT"
echo "  venv       : $VENV_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 1) 探测 Python
PY=""
for cand in python3 python python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver=$("$cand" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$ver" ] && [ "$(printf '%s\n' "3.10" "$ver" | sort -V | head -1)" = "3.10" ]; then
            PY="$cand"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    echo "❌ 未找到 Python 3.10+，请先装 https://www.python.org/downloads/" >&2
    exit 1
fi
echo "✓ python : $($PY -V 2>&1 | head -1)"

# 2) 建 venv（managed python 的 venv 不自带 pip，需 ensurepip）
if [ ! -d "$VENV_DIR" ]; then
    echo "→ 建 venv .venv/"
    "$PY" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m ensurepip --default-pip >/dev/null 2>&1 || true
python -m pip install --upgrade --disable-pip-version-check pip >/dev/null 2>&1 || true
echo "✓ venv ready"

# 3) 装 requirements.txt（含 whiteboard-animator==0.1.1，模型随 pip 从 PyPI 下载 ~83MB）
echo "→ 装 pip 包（首次会从 PyPI 下载白板引擎 + CRAFT 模型，约 83MB）"
python -m pip install --disable-pip-version-check -r "$SCRIPT_DIR/../requirements.txt"

# 4) 验证引擎 + CRAFT 模型随包安装到位
python - <<'PYEOF'
import whiteboard_animator
from pathlib import Path
pkg = Path(whiteboard_animator.__file__).parent
model = pkg / "models" / "craft.onnx"
if model.exists():
    print(f"✓ whiteboard_animator  +  CRAFT 模型 {model.stat().st_size/1e6:.0f}MB")
else:
    print("⚠️  CRAFT 模型未随包安装（请确认 whiteboard-animator==0.1.1）", flush=True)
    raise SystemExit(1)
PYEOF

# 6) ffmpeg 检测
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "⚠️  ffmpeg 未在 PATH；装方式：" >&2
    echo "   macOS : brew install ffmpeg" >&2
    echo "   Linux : sudo apt install ffmpeg  # 或 yum install ffmpeg" >&2
    echo "   Win   : choco install ffmpeg  # 或下载 https://www.gyan.dev/ffmpeg/builds/" >&2
    FFMPEG_OK=0
else
    echo "✓ ffmpeg : $(ffmpeg -version 2>&1 | head -1)"
    FFMPEG_OK=1
fi

# 7) 字体探测
FONT_OK=0
for cand in /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
            /System/Library/Fonts/PingFang.ttc \
            /Library/Fonts/Songti.ttc; do
    if [ -f "$cand" ]; then
        echo "✓ 中文字体 : $cand"
        FONT_OK=1
        break
    fi
done
if [ "$FONT_OK" = "0" ]; then
    echo "⚠️  未探测到系统中文字体；PIL 文字层会失败。请装：sudo apt install fonts-noto-cjk / brew install font-noto-sans-cjk" >&2
fi

# 8) 自检
echo
echo "→ 跑 self_test.py …"
if python "$SKILL_ROOT/scripts/self_test.py" --quick; then
    echo
    echo "✅ 安装完成，可用："
    echo "   source .venv/bin/activate"
    echo "   python scripts/build_narration.py plan.build.json"
    echo "   python scripts/render_explainer.py plan.json --out out/<name>.mp4"
else
    echo "⚠️  自检未全通过，但 skill 已就绪。先排查上方警告再跑出片。" >&2
fi
