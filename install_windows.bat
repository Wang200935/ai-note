@echo off
echo ======================================
echo   AI 語音筆記 - Windows 安裝
echo ======================================

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 需要 Python 3.10+
    echo 請從 https://www.python.org 下載安裝
    pause
    exit /b 1
)
echo Python OK

:: Create venv
if not exist venv (
    echo 建立虛擬環境...
    python -m venv venv
)

call venv\Scripts\activate.bat
echo 虛擬環境啟動

:: Upgrade pip
python -m pip install --upgrade pip -q

:: Install PyTorch (CUDA 12.1 if available, else CPU)
echo 安裝 PyTorch...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121 -q
if errorlevel 1 (
    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu -q
)
echo PyTorch 安裝完成

:: Install requirements
echo 安裝依賴套件...
pip install -r requirements.txt -q
echo 依賴套件安裝完成

echo.
echo ======================================
echo   安裝完成！
echo ======================================
echo.
echo 啟動方式:
echo   venv\Scripts\activate.bat
echo   python main.py
echo.
echo 筆記 LLM 功能需要安裝 Ollama:
echo   https://ollama.com
echo   ollama pull llama3.2
echo.
pause
