import os
from pathlib import Path
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

class Config:
    # Keys
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
    HYDRADB_API_KEY = os.getenv("HYDRADB_API_KEY", "")
    
    # Flask settings
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "videomind-secret-key-default-109823")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    DEBUG = FLASK_ENV == "development"
    
    # DB settings
    # Default to sqlite:///videomind.db inside the videomind directory if not specified
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'videomind.db'}")
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload settings
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
    # Resolve relative uploads folder to base directory
    if not os.path.isabs(UPLOAD_FOLDER):
        UPLOAD_FOLDER = str(BASE_DIR / UPLOAD_FOLDER)
    
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 524288000)) # Default 500MB
