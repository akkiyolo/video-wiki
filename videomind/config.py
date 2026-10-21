import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load env variables from videomind/.env if present (regardless of the working directory).
# Real environment variables (e.g. from Docker) take precedence over the file.
load_dotenv(BASE_DIR / ".env")


def _resolve_dir(value: str, default: Path) -> Path:
    """Resolves a possibly-relative directory against BASE_DIR."""
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


def _resolve_database_url(url: str, data_dir: Path) -> str:
    """
    Resolves relative SQLite paths (e.g. sqlite:///videomind.db) into DATA_DIR so the
    database location does not depend on the current working directory.
    This matches the old Flask-SQLAlchemy behaviour, which stored it in instance/.
    """
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_path = url[len(prefix):]
        if db_path and db_path != ":memory:" and not Path(db_path).is_absolute() and not db_path.startswith("/"):
            return f"{prefix}{(data_dir / db_path).as_posix()}"
    return url


class Config:
    # Keys
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
    HYDRADB_API_KEY = os.getenv("HYDRADB_API_KEY", "")

    # Models
    MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
    WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")

    # Persistent data directory (SQLite database lives here by default)
    DATA_DIR = _resolve_dir(os.getenv("DATA_DIR", ""), BASE_DIR / "instance")

    # DB settings
    DATABASE_URL = _resolve_database_url(
        os.getenv("DATABASE_URL", "sqlite:///videomind.db"), DATA_DIR
    )

    # Upload settings (temporary files; relative paths live inside DATA_DIR so they
    # always land somewhere writable, e.g. the /data volume in Docker)
    _upload_folder = os.getenv("UPLOAD_FOLDER", "uploads")
    UPLOAD_FOLDER = str(
        Path(_upload_folder) if Path(_upload_folder).is_absolute() else DATA_DIR / _upload_folder
    )
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 524288000))  # Default 500MB
