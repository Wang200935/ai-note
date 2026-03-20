#!/bin/bash
# AI 語音筆記 - macOS 一鍵啟動
# 雙擊此檔案即可啟動（無需任何手動操作）

set -e
cd "$(dirname "$0")"

# ── 視覺提示 ────────────────────────────────────────────────────────────────
print_step() { echo ""; echo "▶  $1"; }
print_ok()   { echo "   ✅ $1"; }
print_warn() { echo "   ⚠️  $1"; }

echo "================================================"
echo "   AI 語音筆記 - 啟動中..."
echo "================================================"

# ── 1. 檢查 Python ─────────────────────────────────────────────────────────
print_step "檢查 Python..."
if ! command -v python3 &>/dev/null; then
    osascript -e 'display alert "需要 Python 3.10+" message "請先安裝 Python，點擊「下載」前往官網。" buttons {"下載", "取消"} default button "下載"' 2>/dev/null \
        && open "https://www.python.org/downloads/macos/"
    echo "❌ 請安裝 Python 3.10+ 後再啟動"
    read -p "按 Enter 關閉..."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
MAJOR=$(echo $PY_VER | cut -d. -f1)
MINOR=$(echo $PY_VER | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]); then
    echo "❌ 需要 Python 3.10+，目前版本：$PY_VER"
    open "https://www.python.org/downloads/macos/"
    read -p "按 Enter 關閉..."
    exit 1
fi
print_ok "Python $PY_VER"

# ── 2. 建立虛擬環境 ─────────────────────────────────────────────────────────
print_step "設定虛擬環境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    print_ok "虛擬環境已建立"
else
    print_ok "虛擬環境已存在"
fi

source venv/bin/activate

# ── 3. 安裝依賴套件（首次或更新時） ─────────────────────────────────────────
DEPS_FLAG=".deps_installed"
REQ_HASH=$(md5 -q requirements.txt 2>/dev/null || echo "")
SAVED_HASH=$(cat "$DEPS_FLAG" 2>/dev/null || echo "none")

if [ "$REQ_HASH" != "$SAVED_HASH" ]; then
    print_step "安裝依賴套件（首次執行需要幾分鐘）..."
    pip install --upgrade pip -q

    # PyTorch for Apple Silicon
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ]; then
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
        print_ok "PyTorch (Apple Silicon)"
    else
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
        print_ok "PyTorch (Intel Mac)"
    fi

    pip install -r requirements.txt -q
    echo "$REQ_HASH" > "$DEPS_FLAG"
    print_ok "依賴套件安裝完成"
else
    print_ok "依賴套件已是最新"
fi

# ── 4. 啟動 Ollama（如已安裝）─────────────────────────────────────────────
print_step "檢查 Ollama（AI 筆記功能）..."
if command -v ollama &>/dev/null; then
    if ! pgrep -x "Ollama" &>/dev/null && ! pgrep -x "ollama" &>/dev/null; then
        print_ok "啟動 Ollama 服務..."
        ollama serve &>/dev/null &
        sleep 3
    else
        print_ok "Ollama 已在運行"
    fi

    # 自動下載預設模型（如果還沒有的話）
    if ! ollama list 2>/dev/null | grep -qE "qwen2\.5|llama3|mistral"; then
        print_ok "下載 AI 筆記模型（約 2GB，請稍候）..."
        ollama pull qwen2.5:3b &>/dev/null &
    else
        print_ok "AI 模型已就緒"
    fi
else
    print_warn "未安裝 Ollama（語音轉錄功能仍可正常使用，但無 AI 整理筆記功能）"
    print_warn "安裝 Ollama：https://ollama.com"
fi

# ── 5. 啟動應用 ────────────────────────────────────────────────────────────
echo ""
echo "================================================"
echo "   啟動應用..."
echo "================================================"
echo ""

python main.py

# 如果 app 異常退出，停留在視窗
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 應用程式異常退出"
    read -p "按 Enter 關閉..."
fi
