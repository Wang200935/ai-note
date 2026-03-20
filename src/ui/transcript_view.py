"""
Transcript view - live drafts + final refined segments
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal
from .styles import SPEAKER_COLORS


def _fmt(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


class SegmentWidget(QFrame):
    text_changed = pyqtSignal(int, str)

    def __init__(self, text, start, end,
                 speaker=None, color="#666",
                 db_id=None, live=False, parent=None):
        super().__init__(parent)
        self._db_id  = db_id
        self.is_live = live

        self.setStyleSheet("QFrame { border-bottom: 1px solid #181818; background: transparent; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 7, 16, 7)
        lay.setSpacing(2)

        # Header
        hdr = QHBoxLayout()
        hdr.setSpacing(8)

        if speaker:
            sl = QLabel(speaker)
            sl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
            hdr.addWidget(sl)

        tl = QLabel(_fmt(start))
        tl.setStyleSheet("color: #3a3a3a; font-size: 11px;")
        hdr.addWidget(tl)

        if live:
            bl = QLabel("即時")
            bl.setStyleSheet("color: #f59e0b; font-size: 10px;")
            hdr.addWidget(bl)

        hdr.addStretch()
        lay.addLayout(hdr)

        # Text
        self.edit = QTextEdit()
        self.edit.setPlainText(text)
        self.edit.setStyleSheet("""
            QTextEdit {
                background: transparent;
                border: none;
                padding: 0;
                color: #c8c8c8;
                font-size: 13px;
            }
            QTextEdit:focus {
                background: #141414;
                border-radius: 2px;
                padding: 2px 4px;
            }
        """)
        self.edit.setFixedHeight(52)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.textChanged.connect(self._changed)
        self.edit.document().documentLayout().documentSizeChanged.connect(self._resize)
        lay.addWidget(self.edit)
        self._resize()

    def _resize(self):
        h = max(38, int(self.edit.document().size().height()) + 8)
        self.edit.setFixedHeight(h)

    def _changed(self):
        if self._db_id is not None:
            self.text_changed.emit(self._db_id, self.edit.toPlainText())


class TranscriptView(QWidget):
    segment_edited = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colors:  dict[str, str] = {}
        self._cidx     = 0
        self._widgets: list[SegmentWidget] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { border: none; background: #0d0d0d; }")

        self._body = QWidget()
        self._body.setStyleSheet("background: #0d0d0d;")
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(0)
        self._body_lay.addStretch()

        self._scroll.setWidget(self._body)
        lay.addWidget(self._scroll)

    def _color_for(self, speaker: str) -> str:
        if speaker not in self._colors:
            self._colors[speaker] = SPEAKER_COLORS[self._cidx % len(SPEAKER_COLORS)]
            self._cidx += 1
        return self._colors[speaker]

    def _insert(self, w: SegmentWidget):
        self._widgets.append(w)
        self._body_lay.insertWidget(self._body_lay.count() - 1, w)
        self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()
        )

    def add_live_segment(self, seg):
        w = SegmentWidget(seg.text, seg.start, seg.end, live=True)
        w.text_changed.connect(self.segment_edited)
        self._insert(w)

    def replace_with_final(self, segments: list):
        # Remove all live widgets
        for w in [x for x in self._widgets if x.is_live]:
            self._body_lay.removeWidget(w)
            w.deleteLater()
        self._widgets = [x for x in self._widgets if not x.is_live]
        # Add final
        for seg in segments:
            spk   = getattr(seg, 'speaker', None) or "Speaker"
            color = self._color_for(spk)
            db_id = getattr(seg, 'id', None)
            w = SegmentWidget(seg.text, seg.start, seg.end,
                              speaker=spk, color=color, db_id=db_id)
            w.text_changed.connect(self.segment_edited)
            self._insert(w)

    def load_segments(self, segments: list):
        self.clear()
        for seg in segments:
            spk   = getattr(seg, 'speaker', None) or "Speaker"
            color = self._color_for(spk)
            db_id = getattr(seg, 'id', None)
            w = SegmentWidget(seg.text, seg.start, seg.end,
                              speaker=spk, color=color, db_id=db_id)
            w.text_changed.connect(self.segment_edited)
            self._insert(w)

    def clear(self):
        self._colors.clear()
        self._cidx = 0
        for w in self._widgets:
            self._body_lay.removeWidget(w)
            w.deleteLater()
        self._widgets.clear()
