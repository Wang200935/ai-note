@echo off
chcp 65001 >nul
title AI 語音筆記

echo ================================================
echo    AI 語音筆記 - 啟動中...
echo ================================================

cd /d "%~dp0"

:: ── 1. 檢查 Python ──────────────────────────────────────────────────────────
echo.
echo ▶  檢查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo    ❌ 未安裝 Python，請前往 https://python.org 下載
    start https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version') do set PYVER=%%v
echo    ✅ Python %PYVER%

:: ── 2. 建立虛擬環境 ─────────────────────────────────────────────────────────
echo.
echo ▶  設定虛擬環境...
if not exist venv (
    python -m venv venv
    echo    ✅ 虛擬環境已建立
) else (
    echo    ✅ 虛擬環境已存在
)

call venv\Scripts\activate.bat

:: ── 3. 安裝依賴套件 ─────────────────────────────────────────────────────────
if not exist .deps_installed (
    echo.
    echo ▶  安裝依賴套件（首次執行需要幾分鐘）...
    python -m pip install --upgrade pip -q

    :: Try CUDA, fallback to CPU
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 -q 2>nul
    if errorlevel 1 (
        pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
    )
    echo    ✅ PyTorch 安裝完成

    pip install -r requirements.txt -q
    echo completed > .deps_installed
    echo    ✅ 依賴套件安裝完成
) else (
    echo    ✅ 依賴套件已是最新
)

:: ── 4. 啟動 Ollama ──────────────────────────────────────────────────────────
echo.
echo ▶  檢查 Ollama...
where ollama >nul 2>&1
if not errorlevel 1 (
    tasklist /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
    if errorlevel 1 (
        echo    ✅ 啟動 Ollama 服務...
        start /b ollama serve >nul 2>&1
        timeout /t 3 /nobreak >nul
    ) else (
        echo    ✅ Ollama 已在運行
    )
    ollama list 2>nul | findstr /i "qwen2.5 llama3 mistral" >nul
    if errorlevel 1 (
        echo    ✅ 下載 AI 模型（背景執行）...
        start /b ollama pull qwen2.5:3b >nul 2>&1
    ) else (
        echo    ✅ AI 模型已就緒
    )
) else (
    echo    ⚠️  未安裝 Ollama（語音轉錄仍正常，無 AI 筆記功能）
)

:: ── 5. 啟動應用 ─────────────────────────────────────────────────────────────
echo.
echo ================================================
echo    啟動應用...
echo ================================================
echo.

python main.py

if errorlevel 1 (
    echo.
    echo ❌ 應用程式異常退出
    pause
)
