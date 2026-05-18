import os
import re
from youtube_transcript_api import YouTubeTranscriptApi

class TranscriptionError(Exception):
    """Custom exception raised when transcription fails."""
    pass

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
        api = YouTubeTranscriptApi()
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
        return transcript_text
        
    except Exception as e:
        raise TranscriptionError(f"Failed to fetch YouTube captions: {str(e)}")

def transcribe_file(filepath: str) -> str:
    """
    Transcribes a local audio/video file using faster_whisper base model on CPU.
    Deletes the temporary file after transcription completes or fails.
    """
    try:
        if not os.path.exists(filepath):
            raise TranscriptionError(f"Target file does not exist: {filepath}")
            
        # Import faster_whisper only when needed
        from faster_whisper import WhisperModel
        
        # Initialize whisper model ("base", device="cpu", compute_type="int8" as specified)
        # Note: cpu/int8 is efficient and supported on standard hardware
        model = WhisperModel("base", device="cpu", compute_type="int8")
        
        segments, info = model.transcribe(filepath, beam_size=5)
        
        text_segments = []
        for segment in segments:
            text_segments.append(segment.text)
            
        if not text_segments:
            raise TranscriptionError("Transcription returned empty results.")
            
        transcript = " ".join(text_segments).strip()
        # Clean duplicate spaces
        transcript = re.sub(r'\s+', ' ', transcript)
        return transcript
        
    except Exception as e:
        raise TranscriptionError(f"Whisper transcription failed: {str(e)}")
    finally:
        # Make sure the temporary file is deleted as specified in requirements
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as delete_err:
                print(f"Warning: Failed to delete temp file {filepath}: {delete_err}")
