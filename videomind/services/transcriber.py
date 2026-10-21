import os
import re
import threading
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import IpBlocked, RequestBlocked, TranscriptsDisabled, VideoUnavailable
from youtube_transcript_api.proxies import GenericProxyConfig, WebshareProxyConfig
from config import Config

# Whisper model is expensive to load, so it is created once and shared.
# Transcription runs are serialized because the model is CPU-bound anyway.
_whisper_model = None
_whisper_lock = threading.Lock()

class TranscriptionError(Exception):
    """Custom exception raised when transcription fails."""
    pass

def _get_proxy_config():
    """
    YouTube blocks caption requests from most cloud-provider IPs, so deployments
    can route them through a proxy. Webshare rotating residential proxies are
    preferred; any HTTP(S) proxy URL works as a fallback.
    """
    if Config.WEBSHARE_PROXY_USERNAME and Config.WEBSHARE_PROXY_PASSWORD:
        return WebshareProxyConfig(
            proxy_username=Config.WEBSHARE_PROXY_USERNAME,
            proxy_password=Config.WEBSHARE_PROXY_PASSWORD,
        )
    if Config.YOUTUBE_PROXY_URL:
        return GenericProxyConfig(http_url=Config.YOUTUBE_PROXY_URL, https_url=Config.YOUTUBE_PROXY_URL)
    return None

def extract_youtube_id(url: str) -> str | None:
    """
    Extracts the 11-character YouTube video ID from various YouTube URL formats.
    Handles:
      - youtube.com/watch?v=ID
      - youtu.be/ID
      - youtube.com/shorts/ID
      - youtube.com/embed/ID
      - youtube.com/v/ID
    """
    if not url:
        return None
    
    # Comprehensive YouTube ID regex pattern
    pattern = r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})'
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    
    # Fallback secondary simple patterns
    fallback_patterns = [
        r'v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be\/([a-zA-Z0-9_-]{11})',
        r'shorts\/([a-zA-Z0-9_-]{11})',
        r'embed\/([a-zA-Z0-9_-]{11})'
    ]
    for p in fallback_patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
            
    return None

def get_youtube_thumbnail(video_id: str) -> str:
    """Returns the medium quality thumbnail URL for a YouTube video ID."""
    return f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"

def transcribe_youtube(url: str) -> str:
    """
    Extracts the video ID, fetches captions from YouTube, tries English first, 
    falls back to any available language, joins segments, and returns the transcript.
    """
    video_id = extract_youtube_id(url)
    if not video_id:
        raise TranscriptionError(f"Could not extract a valid YouTube video ID from URL: {url}")
    
    try:
        # Fetch the transcript list from the YouTube Transcript API
        api = YouTubeTranscriptApi(proxy_config=_get_proxy_config())
        transcript_list = api.list(video_id)
        
        # Try English first, then fallback to first available
        try:
            transcript_obj = transcript_list.find_transcript(['en'])
        except Exception:
            # Fallback to the first available transcript (generated, translated, etc.)
            transcript_obj = next(iter(transcript_list))
            
        segments = transcript_obj.fetch()
        if not segments:
            raise TranscriptionError("No transcript segments returned from YouTube API.")
            
        # Clean and join the segments into a single clean string
        transcript_text = " ".join([segment.text.replace('\n', ' ').strip() for segment in segments])
        # Remove extra spaces
        transcript_text = re.sub(r'\s+', ' ', transcript_text).strip()
        if not transcript_text:
            raise TranscriptionError("YouTube returned an empty transcript.")
        return transcript_text
        
    except TranscriptionError:
        raise
    except (RequestBlocked, IpBlocked):
        hint = (
            "the configured proxy was blocked too; try another proxy"
            if _get_proxy_config()
            else "set WEBSHARE_PROXY_USERNAME/WEBSHARE_PROXY_PASSWORD or YOUTUBE_PROXY_URL to route caption requests through a proxy"
        )
        raise TranscriptionError(
            "YouTube is blocking caption requests from this server's IP (common on cloud hosts). "
            f"To fix this, {hint}. Uploading the video file directly also works."
        )
    except TranscriptsDisabled:
        raise TranscriptionError("This video has no captions available. Download it and upload the file instead.")
    except VideoUnavailable:
        raise TranscriptionError("This video is unavailable (private, deleted, or region-locked).")
    except Exception as e:
        raise TranscriptionError(f"Failed to fetch YouTube captions: {str(e)}")

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        # Import faster_whisper only when needed
        from faster_whisper import WhisperModel

        # cpu/int8 is efficient and supported on standard hardware
        _whisper_model = WhisperModel(Config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper_model

def transcribe_file(filepath: str) -> str:
    """
    Transcribes a local audio/video file using faster_whisper on CPU.
    Deletes the temporary file after transcription completes or fails.
    """
    try:
        if not os.path.exists(filepath):
            raise TranscriptionError(f"Target file does not exist: {filepath}")
            
        with _whisper_lock:
            model = _get_whisper_model()
            segments, info = model.transcribe(filepath, beam_size=5)

            # segments is a lazy generator; decoding happens while iterating
            text_segments = [segment.text for segment in segments if segment.text.strip()]
            
        if not text_segments:
            raise TranscriptionError("Transcription returned empty results.")
            
        transcript = " ".join(text_segments).strip()
        # Clean duplicate spaces
        transcript = re.sub(r'\s+', ' ', transcript)
        return transcript
        
    except TranscriptionError:
        raise
    except Exception as e:
        raise TranscriptionError(f"Whisper transcription failed: {str(e)}")
    finally:
        # Make sure the temporary file is deleted as specified in requirements
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as delete_err:
                print(f"Warning: Failed to delete temp file {filepath}: {delete_err}")
