#!/bin/bash
# AI 語音筆記 - macOS 安裝腳本

set -e

echo "======================================"
echo "  AI 語音筆記 - 安裝設定"
echo "======================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 需要 Python 3.10+"
    echo "請從 https://www.python.org 下載安裝"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python $PY_VER"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "建立虛擬環境..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "✅ 虛擬環境啟動"

# Upgrade pip
pip install --upgrade pip -q

# Install PyTorch for Apple Silicon (MPS) or CPU
echo "安裝 PyTorch..."
if [[ $(uname -m) == 'arm64' ]]; then
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
    echo "✅ PyTorch (Apple Silicon CPU)"
else
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
    echo "✅ PyTorch (CPU)"
fi

# Install requirements
echo "安裝依賴套件..."
pip install -r requirements.txt -q
echo "✅ 依賴套件安裝完成"

# Check Ollama
if command -v ollama &> /dev/null; then
    echo "✅ Ollama 已安裝"
    echo ""
    echo "建議下載 LLM 模型 (擇一)："
    echo "  ollama pull llama3.2      (推薦，較快)"
    echo "  ollama pull qwen2.5:7b    (中文效果佳)"
    echo "  ollama pull mistral       (英文效果佳)"
else
    echo "⚠️  Ollama 未安裝"
    echo "請從 https://ollama.com 下載安裝 Ollama"
    echo "安裝後執行: ollama pull llama3.2"
fi

echo ""
echo "======================================"
echo "  安裝完成！"
echo "======================================"
echo ""
echo "啟動方式："
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "說話人辨識設定（可選）："
echo "  需要 HuggingFace Token"
echo "  前往 https://huggingface.co/settings/tokens 取得"
echo "  並同意 pyannote 模型使用條款："
echo "  https://huggingface.co/pyannote/speaker-diarization-3.1"
