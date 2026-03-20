"""
SQLite database for recording history and transcripts
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from pathlib import Path
import json


DB_PATH = Path(__file__).parent.parent.parent / "data" / "history.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

Base = declarative_base()


class Recording(Base):
    __tablename__ = "recordings"

    id = Column(Integer, primary_key=True)
    title = Column(String(256), nullable=False)
    audio_path = Column(String(512))
    mode = Column(String(32), default='class')  # 'class' or 'meeting'
    language = Column(String(32))
    duration = Column(Float)
    created_at = Column(DateTime, default=datetime.now)
    notes = Column(Text)  # LLM-generated notes (Markdown)

    segments = relationship("Segment", back_populates="recording", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'audio_path': self.audio_path,
            'mode': self.mode,
            'language': self.language,
            'duration': self.duration,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'notes': self.notes,
        }


class Segment(Base):
    __tablename__ = "segments"

    id = Column(Integer, primary_key=True)
    recording_id = Column(Integer, ForeignKey("recordings.id"), nullable=False)
    start = Column(Float, nullable=False)
    end = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    speaker = Column(String(64))

    recording = relationship("Recording", back_populates="segments")

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'start': self.start,
            'end': self.end,
            'text': self.text,
            'speaker': self.speaker,
        }


class Database:
    def __init__(self):
        engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        self.session = Session()

    def save_recording(self, title: str, audio_path: str, mode: str,
                       language: str, duration: float, segments: list,
                       notes: str = "") -> int:
        rec = Recording(
            title=title,
            audio_path=audio_path,
            mode=mode,
            language=language,
            duration=duration,
            notes=notes,
        )
        self.session.add(rec)
        self.session.flush()

        for seg in segments:
            db_seg = Segment(
                recording_id=rec.id,
                start=seg.start,
                end=seg.end,
                text=seg.text,
                speaker=seg.speaker,
            )
            self.session.add(db_seg)

        self.session.commit()
        return rec.id

    def update_notes(self, recording_id: int, notes: str):
        rec = self.session.get(Recording, recording_id)
        if rec:
            rec.notes = notes
            self.session.commit()

    def update_segment(self, segment_id: int, text: str):
        seg = self.session.get(Segment, segment_id)
        if seg:
            seg.text = text
            self.session.commit()

    def get_all_recordings(self) -> list[Recording]:
        return self.session.query(Recording).order_by(Recording.created_at.desc()).all()

    def get_recording(self, recording_id: int) -> Recording | None:
        return self.session.get(Recording, recording_id)

    def delete_recording(self, recording_id: int):
        rec = self.session.get(Recording, recording_id)
        if rec:
            self.session.delete(rec)
            self.session.commit()
