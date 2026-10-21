import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import Config

Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class VideoSession(Base):
    __tablename__ = 'video_sessions'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    source_type = Column(String(50), nullable=False)  # "youtube" or "file"
    source_ref = Column(Text, nullable=False)  # YouTube URL or original filename
    thumbnail = Column(Text, nullable=True)  # YouTube thumbnail URL or None
    transcript = Column(Text, nullable=True)  # full transcript string
    word_count = Column(Integer, default=0)
    status = Column(String(50), default="processing")  # "processing", "ready", "error"
    error_msg = Column(Text, nullable=True)
    hydra_ok = Column(Boolean, default=False)
    article_content = Column(Text, nullable=True)  # Generated Wikipedia Article markdown
    created_at = Column(DateTime, default=_utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "thumbnail": self.thumbnail,
            "transcript": self.transcript,
            "article_content": self.article_content,
            "word_count": self.word_count,
            "status": self.status,
            "error_msg": self.error_msg,
            "hydra_ok": self.hydra_ok,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


_is_sqlite = Config.DATABASE_URL.startswith("sqlite")
if _is_sqlite:
    # Make sure the folder holding the SQLite file exists before connecting
    _db_file = Config.DATABASE_URL[len("sqlite:///"):]
    if _db_file and _db_file != ":memory:":
        Path(_db_file).parent.mkdir(parents=True, exist_ok=True)

# SQLite connections are shared between the request threadpool and background workers
engine = create_engine(
    Config.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    Base.metadata.create_all(bind=engine)
