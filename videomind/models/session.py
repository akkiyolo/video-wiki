import uuid
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class VideoSession(db.Model):
    __tablename__ = 'video_sessions'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(255), nullable=False)
    source_type = db.Column(db.String(50), nullable=False)  # "youtube" or "file"
    source_ref = db.Column(db.Text, nullable=False)  # YouTube URL or original filename
    thumbnail = db.Column(db.Text, nullable=True)  # YouTube thumbnail URL or None
    transcript = db.Column(db.Text, nullable=True)  # full transcript string
    word_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default="processing")  # "processing", "ready", "error"
    error_msg = db.Column(db.Text, nullable=True)
    hydra_ok = db.Column(db.Boolean, default=False)
    article_content = db.Column(db.Text, nullable=True)  # Generated Wikipedia Article markdown
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
