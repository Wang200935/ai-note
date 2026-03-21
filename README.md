# AI 語音筆記 - Transcribe

一個跨平台的 AI 語音轉錄應用，支援 macOS 和 Windows。使用先進的深度學習模型進行語音識別和說話人分辨。

![Python](https://img.shields.io/badge/Python-3.9+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows-lightgray)

## 功能特性

✨ **核心功能**

- 🎤 實時語音錄製 & 系統音頻捕捉
- 🤖 AI 語音識別 (Faster Whisper)
- 👥 說話人自動識別 (Speaker Diarization)
- 📝 文字編輯 & 格式化
- 💾 多格式導出 (Word、PDF、Markdown)
- 🗄️ SQLite 本地數據庫存儲

## 系統需求

- **Python**: 3.9+
- **OS**: macOS 10.13+ 或 Windows 10+
- **RAM**: 至少 4GB (建議 8GB+)
- **GPU** (可選): NVIDIA CUDA 11.8+ (加速語音識別)

## 安裝步驟

### macOS

```bash
# 1. 克隆倉庫
git clone https://github.com/Wang200935/ai-note.git
cd ai轉錄

# 2. 運行安裝腳本
bash install.sh

# 3. 啟動應用
bash 啟動.command
```

### Windows

```bash
# 1. 克隆倉庫
git clone https://github.com/Wang200935/ai-note.git
cd ai轉錄

# 2. 運行安裝腳本
install_windows.bat

# 3. 運行應用
啟動.bat
```

### 手動安裝

```bash
# 創建虛擬環境
python3 -m venv venv

# 啟動虛擬環境
source venv/bin/activate  # macOS/Linux
# 或
venv\Scripts\activate  # Windows

# 安裝依賴
pip install -r requirements.txt

# 下載模型 (首次運行時自動下載)
python main.py
```

## 使用說明

### 啟動應用

**macOS**:

```bash
bash 啟動.command
```

**Windows**:

```bash
啟動.bat
```

或直接使用 Python:

```bash
python main.py
```

### 首次設置

1. 啟動應用時會出現設置面板
2. 選擇語音模型大小:
   - `tiny`: 最快，準確率最低 (推薦資源受限時使用)
   - `small`: 平衡性能與準確率 (推薦)
   - `medium/large`: 最高準確率，需要更多資源

3. 設置說話人分辨 (可選):
   - 自動偵測錄音中的不同說話者
   - 支援本地方案和線上方案

### 基本操作

1. **錄製音頻**
   - 點擊 🎤 開始錄製
   - 點擊 ⏹️ 停止錄製

2. **捕捉系統音頻**
   - 選擇"系統音頻"進行錄製
   - 適合錄製線上會議、視頻等

3. **轉錄文本**
   - 自動轉錄或手動點擊轉錄按鈕
   - 識別說話人 (如已啟用)

4. **編輯 & 導出**
   - 在編輯器中調整文本
   - 導出為 Word、PDF 或 Markdown

## 項目結構

```
ai-note/
├── src/
│   ├── audio/              # 音頻錄製与捕捉
│   │   ├── recorder.py    # 麥克風錄音
│   │   └── system_audio.py # 系統音頻捕捉
│   ├── transcription/      # 語音識別和分辨
│   │   ├── engine.py      # Whisper 引擎
│   │   ├── diarizer.py    # 說話人分辨
│   │   └── streaming.py   # 實時流處理
│   ├── storage/           # 數據存儲
│   │   └── database.py    # SQLite 數據庫
│   ├── export/            # 導出功能
│   │   └── exporter.py    # 多格式導出
│   ├── notes/             # 筆記管理
│   │   └── organizer.py   # 筆記組織
│   └── ui/                # 用戶界面
│       ├── main_window.py # 主窗口
│       ├── setup_dialog.py # 設置對話框
│       ├── transcript_view.py # 轉錄視圖
│       └── styles.py       # 樣式表
├── main.py                 # 應用入口
├── requirements.txt        # Python 依賴
├── install.sh              # macOS 安裝腳本
├── install_windows.bat     # Windows 安裝腳本
└── README.md               # 本文件
```

## 依賴項

### 語音識別

- **faster-whisper**: 快速 Whisper 實現
- **torch** & **torchaudio**: PyTorch 深度學習框架

### 說話人分辨

- **simple-diarizer**: 輕量級本地分辨方案 (推薦)
- **pyannote.audio**: 高精度分辨方案 (可選，需 HuggingFace token)

### UI & 存儲

- **PyQt6**: 跨平台 GUI 框架
- **SQLAlchemy**: ORM 數據庫抽象層
- **python-docx**, **reportlab**, **fpdf2**: 文檔導出

### 音頻處理

- **sounddevice**: 麥克風I/O
- **soundfile**: WAV 文件處理
- **numpy**, **scipy**: 信號處理

## 配置

### 環境變數

創建 `.env` 文件:

```
WHISPER_MODEL=small
DIARIZER_METHOD=simple  # 或 pyannote
HF_TOKEN=your_huggingface_token  # 如使用 pyannote
```

## 常見問題

### 1. "模型下載失敗"

- 確保網路良好
- 模型會存儲在 `models/` 目錄
- 首次下載可能需要 5-10 分鐘

### 2. "沒有聲音輸入"

- macOS: 檢查系統隱私設置 > 麥克風
- Windows: 檢查音頻設備設置
- 確保正確選擇了audio device

### 3. "轉錄速度很慢"

- 減小模型大小 (tiny/small vs medium/large)
- 使用 NVIDIA GPU 加速 (需安裝 CUDA)
- 增加系統 RAM

### 4. "說話人分辨不准確"

- 嘗試 pyannote 方案 (更準確但需 token)
- 確保音頻質量良好
- 多人場景效果最佳

## 開發

### 設置開發環境

```bash
# 克隆並進入項目
git clone https://github.com/Wang200935/ai-note.git
cd ai-note

# 創建虛擬環境
python3 -m venv venv_dev
source venv_dev/bin/activate

# 安裝依賴 (含開發工具)
pip install -r requirements.txt
pip install pytest black flake8  # 開發工具
```

### 運行測試

```bash
pytest tests/
```

### 代碼風格

遵循 PEP 8:

```bash
black src/
flake8 src/
```

## 已知限制

- ⚠️ 支援語言: 英文、中文、日文等 (Whisper 支援 99+ 語言)
- ⚠️ 說話人分辨: 最多支援約 10 位說話者
- ⚠️ 檔案大小: 建議單次錄製 < 1 小時


## 貢獻

歡迎提交 Issue 和 Pull Request！

1. Fork 本倉庫
2. 建立功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 開啟 Pull Request

## 聯繫方式

有問題或建議？歡迎開啟 GitHub Issue。

---

**最後更新**: 2026-03-21
**版本**: 1.0.0
