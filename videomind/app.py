import asyncio
import json
import os
import queue
import re
import threading
import unicodedata
import uuid
from contextlib import asynccontextmanager
from typing import List

import requests
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from config import BASE_DIR, Config
from models.session import SessionLocal, VideoSession, init_db
from services import transcriber, hydradb, mistral

GLOBAL_TENANT_ID = "global_videowiki_tenant"

# Max number of previous chat turns forwarded to the LLM (keeps prompts inside the context window)
MAX_HISTORY_TURNS = 20

# Global status queues dict for SSE tracking.
# NOTE: this is in-process state, so the app must run with a single worker process.
status_queues: dict[str, queue.Queue] = {}

# Sessions whose missing article is currently being regenerated in the background
_article_jobs: set[str] = set()
_article_jobs_lock = threading.Lock()
# Last article-generation error per session (in memory; cleared on success or retry)
_article_errors: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    init_db()
    # Any session still "processing" at startup was interrupted by a restart and will never finish
    with SessionLocal() as db:
        stale = db.query(VideoSession).filter(VideoSession.status == "processing").all()
        for s in stale:
            s.status = "error"
            s.error_msg = "Processing was interrupted by a server restart. Please ingest the video again."
        if stale:
            db.commit()
    yield


app = FastAPI(title="VideoWiki", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def url_for(name: str, **params) -> str:
    """
    Template helper returning a root-relative URL (works behind HTTPS proxies).
    Accepts Flask-style `filename=` for static files.
    """
    if "filename" in params:
        params["path"] = params.pop("filename")
    return str(app.url_path_for(name, **{k: str(v) for k, v in params.items()}))


templates.env.globals["url_for"] = url_for


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return validation errors as {"error": ...} so the frontend can display them."""
    errors = exc.errors()
    if errors:
        first = errors[0]
        field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"Invalid request: {field} {first.get('msg', '')}".strip() if field else first.get("msg", "Invalid request")
    else:
        msg = "Invalid request"
    return JSONResponse({"error": msg}, status_code=400)


def error_response(msg: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=status_code)


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def secure_filename(filename: str) -> str:
    """Reduces an uploaded filename to a safe ASCII basename for storage on disk."""
    filename = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    filename = filename.replace("\\", "/").split("/")[-1]
    filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename).strip("._")
    return filename[:150] or "upload"


def get_youtube_title(video_id):
    """
    Attempts to fetch a clean YouTube video title using YouTube oEmbed.
    Falls back gracefully to a generic title if the request fails.
    """
    try:
        url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        response = requests.get(url, timeout=5)
        if response.ok:
            return response.json().get("title", f"YouTube Video ({video_id})")
    except Exception:
        pass
    return f"YouTube Video ({video_id})"


def start_background(target, *args):
    thread = threading.Thread(target=target, args=args, daemon=True)
    thread.start()


def process_session(session_id, source_type, source_data):
    """
    Background worker thread to transcribe video/audio and upload to HydraDB.
    Communicates progress using a thread-safe Queue.
    """
    q = status_queues.get(session_id)

    def emit(step, status, msg=None, **kwargs):
        if q:
            event_data = {"step": step, "status": status}
            if msg:
                event_data["msg"] = msg
            event_data.update(kwargs)
            q.put(event_data)

    db = SessionLocal()
    try:
        # 1. Fetch Session from Database
        session = db.get(VideoSession, session_id)
        if not session:
            emit("error", "error", f"Session {session_id} not found in database.")
            return

        # Step 1: Transcribe Started
        emit("transcribe", "active", "Initializing transcription pipeline...")

        # Step 2: Perform transcription based on source type
        if source_type == "youtube":
            emit("transcribe", "active", "Fetching YouTube captions...")
            transcript = transcriber.transcribe_youtube(source_data)
        else:  # file upload
            emit("transcribe", "active", "Running local Whisper model... This may take a moment.")
            transcript = transcriber.transcribe_file(source_data)

        word_count = len(transcript.split()) if transcript else 0

        # Step 3: Update DB with transcript details
        session.transcript = transcript
        session.word_count = word_count
        session.status = "processing"
        db.commit()

        emit("transcribe", "done", f"Transcript ready ({word_count} words)")

        # Step 4: Storing in HydraDB Started
        emit("hydra", "active", "Creating HydraDB memory infrastructure...")

        # Step 5 & 6: Call HydraDB API
        hydra_created = hydradb.create_tenant(session_id)
        hydra_stored = False

        if hydra_created:
            emit("hydra", "active", "Uploading transcript memories to HydraDB...")
            hydra_stored = hydradb.store_memory(session_id, transcript, session.title)

            # Also store in global tenant for Cross-Video Wikipedia Search!
            emit("hydra", "active", "Indexing memories in Global Wikipedia tenant...")
            if hydradb.create_tenant(GLOBAL_TENANT_ID):
                hydradb.store_global_chunks(GLOBAL_TENANT_ID, session_id, session.title, transcript)
            else:
                print(f"Failed to prepare global tenant for session {session_id}")

        # Step 7: Update DB record status
        session.hydra_ok = hydra_created and hydra_stored
        session.status = "processing"  # keep processing until article is synthesized!
        db.commit()

        # Step 8: Emit Hydra done
        if session.hydra_ok:
            emit("hydra", "done", "Stored in HydraDB")
        else:
            emit("hydra", "done", "Stored transcript locally (HydraDB skipped)")

        # Wikipedia Article Synthesis
        emit("article", "active", "Synthesizing full Wikipedia-style article using Mistral...")
        try:
            session.article_content = mistral.generate_wikipedia_article(transcript, session.title)
            _article_errors.pop(session_id, None)
            article_msg = "Wikipedia article successfully generated!"
        except Exception as article_err:
            print(f"Failed to generate article: {article_err}")
            _article_errors[session_id] = str(article_err)
            article_msg = "Stored transcript only (article generation failed, you can retry from the article page)"

        session.status = "ready"
        db.commit()
        emit("article", "done", article_msg)

        # Step 9: Emit done
        emit("done", "done", session_id=session_id)

    except Exception as e:
        # Rollback database on error
        db.rollback()
        try:
            session = db.get(VideoSession, session_id)
            if session:
                session.status = "error"
                session.error_msg = str(e)
                db.commit()
        except Exception as db_err:
            print(f"Failed to update error status for session {session_id}: {db_err}")

        emit("error", "error", msg=str(e))
    finally:
        db.close()
        # Any SSE listener already holds a reference to the queue; late listeners read the DB status
        status_queues.pop(session_id, None)


def regenerate_article(session_id):
    """Background failsafe: synthesizes a missing article for a ready session."""
    try:
        with SessionLocal() as db:
            session = db.get(VideoSession, session_id)
            if not session or session.article_content:
                return
            session.article_content = mistral.generate_wikipedia_article(session.transcript or "", session.title)
            db.commit()
        _article_errors.pop(session_id, None)
    except Exception as article_err:
        print(f"Failsafe article generation failed for session {session_id}: {article_err}")
        _article_errors[session_id] = str(article_err)
    finally:
        with _article_jobs_lock:
            _article_jobs.discard(session_id)


def start_article_job(session_id, retry=False) -> bool:
    """
    Starts background article generation unless one is already running.
    A previously failed session is only retried when explicitly asked, so page
    refreshes don't keep hammering a rate-limited API.
    """
    with _article_jobs_lock:
        if session_id in _article_jobs:
            return True
        if session_id in _article_errors and not retry:
            return False
        _article_errors.pop(session_id, None)
        _article_jobs.add(session_id)
    start_background(regenerate_article, session_id)
    return True


def article_state(session):
    """Article status for the page: ready / generating / failed / unavailable."""
    if (session.article_content or "").strip():
        return {"status": "ready", "article_content": session.article_content}
    if session.id in _article_jobs:
        return {"status": "generating"}
    if session.id in _article_errors:
        return {"status": "failed", "error": _article_errors[session.id]}
    return {"status": "unavailable" if not session.transcript else "generating"}


def list_sessions(db):
    return db.query(VideoSession).order_by(VideoSession.created_at.desc()).all()


def create_session(**fields) -> str:
    """Creates a DB session record with status="processing" and registers its SSE queue."""
    with SessionLocal() as db:
        session = VideoSession(status="processing", hydra_ok=False, **fields)
        db.add(session)
        db.commit()
        session_id = session.id
    status_queues[session_id] = queue.Queue()
    return session_id


# ==========================================
# WEB ROUTES
# ==========================================

@app.get("/", name="index")
def index(request: Request):
    """Renders index.html (upload page) with all sessions passed to the sidebar."""
    with SessionLocal() as db:
        sessions = list_sessions(db)
    return templates.TemplateResponse(request, "index.html", {"sessions": sessions, "page": "upload"})


@app.get("/session/{id}", name="session_detail")
def session_detail(request: Request, id: str):
    """Renders chat.html for the given session with all sessions passed to the sidebar."""
    with SessionLocal() as db:
        sessions = list_sessions(db)
        session = db.get(VideoSession, id)
    if not session:
        return RedirectResponse(url_for("index"), status_code=303)

    # Failsafe: if status is ready but article_content is empty, regenerate it in the
    # background instead of blocking this page on a slow LLM call
    if session.status == "ready" and not (session.article_content or "").strip() and session.transcript:
        start_article_job(id)

    return templates.TemplateResponse(
        request, "chat.html", {"sessions": sessions, "session": session, "page": "chat"}
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ==========================================
# API ENDPOINTS
# ==========================================

class YoutubeIngestRequest(BaseModel):
    url: str


class ChatTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = []


class WikiSearchRequest(BaseModel):
    query: str


@app.post("/api/ingest/youtube")
def ingest_youtube(body: YoutubeIngestRequest):
    """Accepts JSON {url}, returns {session_id}, starts background processing."""
    url = body.url.strip()
    if not url:
        return error_response("YouTube URL is required", 400)

    video_id = transcriber.extract_youtube_id(url)
    if not video_id:
        return error_response("Could not extract a valid YouTube video ID. Check the URL.", 400)

    session_id = create_session(
        title=get_youtube_title(video_id)[:255],
        source_type="youtube",
        source_ref=url,
        thumbnail=transcriber.get_youtube_thumbnail(video_id),
    )

    # Kick off background processing and return the session_id immediately
    start_background(process_session, session_id, "youtube", url)
    return {"session_id": session_id}


def save_upload(src, dest_path: str, max_bytes: int) -> int:
    """Copies the uploaded file to disk, enforcing the size limit. Returns bytes written."""
    written = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("File exceeds the maximum upload size.")
                out.write(chunk)
    except Exception:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise
    return written


@app.post("/api/ingest/file")
async def ingest_file(request: Request):
    """Accepts multipart file upload, returns {session_id}, starts background processing."""
    max_bytes = Config.MAX_CONTENT_LENGTH
    content_length = request.headers.get("content-length")
    # Reject oversize uploads before reading the body (allow some multipart overhead)
    if content_length and content_length.isdigit() and int(content_length) > max_bytes + 1024 * 1024:
        return error_response(f"File exceeds the {max_bytes // (1024 * 1024)}MB upload limit.", 413)

    try:
        form = await request.form(max_files=1)
    except Exception as e:
        return error_response(f"Invalid upload: {e}", 400)

    try:
        file = form.get("file")
        if not isinstance(file, UploadFile):
            return error_response("No file part in the request.", 400)
        if not file.filename:
            return error_response("No file selected.", 400)

        original_name = os.path.basename(file.filename.replace("\\", "/"))
        # Generate unique filename to avoid path collisions
        filepath = os.path.join(Config.UPLOAD_FOLDER, f"{uuid.uuid4()}_{secure_filename(original_name)}")

        try:
            await run_in_threadpool(save_upload, file.file, filepath, max_bytes)
        except ValueError as e:
            return error_response(str(e), 413)
        except Exception as e:
            return error_response(f"Failed to save file: {e}", 500)
    finally:
        await form.close()

    session_id = await run_in_threadpool(
        create_session,
        title=original_name[:255],
        source_type="file",
        source_ref=original_name,
        thumbnail=None,
    )

    # Kick off background processing and return the session_id immediately
    start_background(process_session, session_id, "file", filepath)
    return {"session_id": session_id}


def get_session_status(session_id):
    with SessionLocal() as db:
        session = db.get(VideoSession, session_id)
        if not session:
            return None, None
        return session.status, session.error_msg


@app.get("/api/ingest/status/{id}")
async def ingest_status(request: Request, id: str):
    """SSE stream of processing progress events for a session."""

    async def event_generator():
        # Grab the queue before checking the DB so no terminal event can be missed
        q = status_queues.get(id)

        status, error_msg = await run_in_threadpool(get_session_status, id)
        if status is None:
            yield sse_event({"step": "error", "msg": "Session not found"})
            return
        # If it's already done or failed before SSE connected
        if status == "ready":
            yield sse_event({"step": "done", "session_id": id})
            return
        if status == "error":
            yield sse_event({"step": "error", "msg": error_msg or "Processing failed"})
            return

        loop = asyncio.get_running_loop()
        last_sent = loop.time()
        last_db_check = loop.time()

        while True:
            if await request.is_disconnected():
                break

            event = None
            if q is not None:
                try:
                    event = q.get_nowait()
                except queue.Empty:
                    pass

            if event is not None:
                yield sse_event(event)
                last_sent = loop.time()
                if event.get("step") in ("done", "error"):
                    break
                continue

            # No live queue (e.g. reconnect after the worker finished): fall back to polling the DB
            if q is None and loop.time() - last_db_check >= 2:
                last_db_check = loop.time()
                status, error_msg = await run_in_threadpool(get_session_status, id)
                if status == "ready":
                    yield sse_event({"step": "done", "session_id": id})
                    break
                if status != "processing":
                    yield sse_event({"step": "error", "msg": error_msg or "Processing failed"})
                    break

            if loop.time() - last_sent >= 15:
                yield ": keepalive\n\n"
                last_sent = loop.time()

            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.post("/api/chat/{session_id}")
def chat(session_id: str, body: ChatRequest):
    """Accepts JSON {message, history[]}, streams Mistral response via SSE."""
    with SessionLocal() as db:
        session = db.get(VideoSession, session_id)
    if not session:
        return error_response("Session not found", 404)

    if session.status != "ready":
        return error_response("Session is not ready for chat yet", 400)

    message = body.message.strip()
    if not message:
        return error_response("Message is required", 400)

    history = [turn.model_dump() for turn in body.history[-MAX_HISTORY_TURNS:]]

    # Retrieve context from HydraDB if successfully set up, otherwise fallback
    context = ""
    if session.hydra_ok:
        context = hydradb.recall_context(session_id, message)

    if not context:
        # Fall back to first 8000 chars of local transcript
        context = (session.transcript or "")[:8000]

    def generate_response():
        try:
            for token in mistral.stream_chat(message, context, history):
                yield sse_event({"chunk": token})
            yield sse_event({"done": True})
        except Exception as e:
            yield sse_event({"error": str(e)})

    return StreamingResponse(generate_response(), media_type="text/event-stream", headers=SSE_HEADERS)


@app.get("/api/sessions")
def get_sessions():
    """Returns JSON list of all sessions (for sidebar/UI updating)."""
    with SessionLocal() as db:
        return [s.to_dict() for s in list_sessions(db)]


@app.get("/api/session/{id}/article")
def get_article(id: str):
    """Article generation status, polled by the article page while it is empty."""
    with SessionLocal() as db:
        session = db.get(VideoSession, id)
    if not session:
        return error_response("Session not found", 404)
    return article_state(session)


@app.post("/api/session/{id}/article")
def retry_article(id: str):
    """(Re)starts article generation for a session whose article is missing."""
    with SessionLocal() as db:
        session = db.get(VideoSession, id)
    if not session:
        return error_response("Session not found", 404)
    if not session.transcript:
        return error_response("This session has no transcript to build an article from.", 400)
    if not (session.article_content or "").strip():
        start_article_job(id, retry=True)
    return article_state(session)


@app.delete("/api/session/{id}")
def delete_session(id: str):
    """Deletes session from DB + HydraDB if possible."""
    with SessionLocal() as db:
        session = db.get(VideoSession, id)
        if not session:
            return error_response("Session not found", 404)

        # Attempt to delete from HydraDB
        hydradb.delete_tenant(id)

        # Remove from DB
        try:
            db.delete(session)
            db.commit()
        except Exception as e:
            db.rollback()
            return error_response(f"Failed to delete session: {e}", 500)

    # Clean up in-memory state for the session
    status_queues.pop(id, None)
    _article_errors.pop(id, None)
    return {"success": True}


def parse_global_context(context: str):
    """
    Extracts (title, session_id, content) tuples from the global tenant recall text.
    Chunks are stored as "Article Title: ... | Session ID: ... | Content: ...".
    """
    # primary regex parser
    matches = re.finditer(
        r"Article Title:\s*(.*?)\s*\|\s*Session ID:\s*(.*?)\s*\|\s*Content:\s*(.*?)(?=Article Title:|$)",
        context,
        re.DOTALL | re.IGNORECASE,
    )
    parsed = [(m.group(1).strip(), m.group(2).strip(), m.group(3).strip()) for m in matches]
    if parsed:
        return parsed

    # secondary fallback line parser
    for line in context.split("\n"):
        if "Article Title:" in line and "Session ID:" in line:
            parts = line.split("|")
            if len(parts) >= 3:
                parsed.append((
                    parts[0].replace("Article Title:", "").strip(),
                    parts[1].replace("Session ID:", "").strip(),
                    "|".join(parts[2:]).replace("Content:", "", 1).strip(),
                ))
    return parsed


@app.post("/api/wiki/search")
def wiki_search(body: WikiSearchRequest):
    """Performs semantic cross-video vector search across all indexed Video Wikipedia articles."""
    query = body.query.strip()
    if not query:
        return error_response("Query is required", 400)

    context = hydradb.recall_context(GLOBAL_TENANT_ID, query)
    if not context:
        return {"results": []}

    results = []
    seen_sessions = set()

    with SessionLocal() as db:
        for title, sid, content in parse_global_context(context):
            if not sid or sid in seen_sessions:
                continue
            seen_sessions.add(sid)
            # Skip results whose session has since been deleted (global chunks are not removed)
            session = db.get(VideoSession, sid)
            if not session:
                continue
            results.append({
                "session_id": sid,
                "session_title": title or session.title,
                "thumbnail": session.thumbnail,
                "source_type": session.source_type,
                "snippet": content[:240] + "..." if len(content) > 240 else content
            })

    return {"results": results}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
