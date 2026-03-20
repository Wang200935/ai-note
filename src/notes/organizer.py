"""
Note organizer - uses local Ollama LLM to turn transcripts into structured notes
"""
from PyQt6.QtCore import QObject, pyqtSignal, QThread
import json


MODELS = ['llama3.2', 'llama3.1', 'mistral', 'qwen2.5', 'phi3']

CLASS_NOTES_PROMPT = """你是一位專業的課堂筆記整理助手。
請將以下課堂逐字稿整理成清晰、有結構的筆記。

要求：
1. 提取主要主題和子主題
2. 列出重要概念、定義
3. 標記重要術語（用**粗體**）
4. 整理成 Markdown 格式
5. 在最後加上「重點摘要」區塊

逐字稿：
{transcript}

請輸出整理好的筆記："""

MEETING_NOTES_PROMPT = """你是一位專業的會議記錄整理助手。
請將以下會議逐字稿整理成會議記錄。

要求：
1. 會議摘要（2-3句）
2. 討論重點（按主題分組）
3. 決議事項（如有）
4. 待辦事項（如有）
5. 使用 Markdown 格式

逐字稿：
{transcript}

請輸出整理好的會議記錄："""


def format_transcript_for_llm(segments: list) -> str:
    """Format transcript segments into readable text."""
    lines = []
    for seg in segments:
        speaker = getattr(seg, "speaker", None) or "講者"
        lines.append(f"[{seg.start:.1f}s] {speaker}: {seg.text}")
    return "\n".join(lines)


class NoteThread(QThread):
    chunk_ready = pyqtSignal(str)   # streaming output
    finished = pyqtSignal(str)      # complete notes
    error = pyqtSignal(str)

    def __init__(self, transcript: str, mode: str, model: str):
        super().__init__()
        self.transcript = transcript
        self.mode = mode
        self.model = model

    def run(self):
        try:
            import ollama

            prompt_template = CLASS_NOTES_PROMPT if self.mode == 'class' else MEETING_NOTES_PROMPT
            prompt = prompt_template.format(transcript=self.transcript)

            full_text = ""
            stream = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in stream:
                # ollama >= 0.2: ChatResponse object; older: dict
                if hasattr(chunk, "message"):
                    delta = chunk.message.content or ""
                else:
                    delta = chunk.get("message", {}).get("content", "")
                if delta:
                    full_text += delta
                    self.chunk_ready.emit(delta)

            self.finished.emit(full_text)

        except Exception as e:
            self.error.emit(f"筆記整理失敗: {e}")


class NoteOrganizer(QObject):
    """Organizes transcripts into structured notes using local Ollama."""
    chunk_ready = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, model: str = 'llama3.2'):
        super().__init__()
        self._model = model
        self._thread: NoteThread | None = None

    def get_available_models(self) -> list[str]:
        """Return installed Ollama models."""
        try:
            import ollama
            result = ollama.list()
            raw = result.models if hasattr(result, "models") else result.get("models", [])
            return [m.model if hasattr(m, "model") else m.get("name", "") for m in raw]
        except Exception:
            return []

    def organize(self, segments: list, mode: str = 'class'):
        """
        Organize transcript into notes.
        mode: 'class' for classroom notes, 'meeting' for meeting minutes
        """
        if self._thread and self._thread.isRunning():
            return

        transcript = format_transcript_for_llm(segments)
        self._thread = NoteThread(transcript, mode, self._model)
        self._thread.chunk_ready.connect(self.chunk_ready)
        self._thread.finished.connect(self.finished)
        self._thread.error.connect(self.error)
        self._thread.start()

    def set_model(self, model: str):
        self._model = model
