import os
import queue
import threading
import json
import uuid
import requests
import re
from flask import Flask, render_template, request, jsonify, Response, current_app, redirect, url_for
from werkzeug.utils import secure_filename

from config import Config
from models.session import db, VideoSession
from services import transcriber, hydradb, mistral

app = Flask(__name__)
app.config.from_object(Config)

# Initialize SQLAlchemy
db.init_app(app)

# Ensure upload directory exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Global status queues dict for SSE tracking
status_queues = {}

# Create tables if not exists
with app.app_context():
    db.create_all()

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

def process_session(flask_app, session_id, source_type, source_data):
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

    with flask_app.app_context():
        try:
            # 1. Fetch Session from Database
            session = db.session.get(VideoSession, session_id)
            if not session:
                emit("error", "error", f"Session {session_id} not found in database.")
                return
            
            # Step 1: Transcribe Started
            emit("transcribe", "active", "Initializing transcription pipeline...")
            
            # Step 2: Perform transcription based on source type
            transcript = ""
            if source_type == "youtube":
                emit("transcribe", "active", "Fetching YouTube captions...")
                transcript = transcriber.transcribe_youtube(source_data)
            else:  # file upload
                emit("transcribe", "active", "Running local Whisper model (base)... This may take a moment.")
                transcript = transcriber.transcribe_file(source_data)
            
            word_count = len(transcript.split()) if transcript else 0
            
            # Step 3: Update DB with transcript details
            session.transcript = transcript
            session.word_count = word_count
            session.status = "processing"
            db.session.commit()
            
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
                try:
                    emit("hydra", "active", "Indexing memories in Global Wikipedia tenant...")
                    # 1. Create global tenant if not already ready (returns immediately if already exists)
                    hydradb.create_tenant("global_videowiki_tenant")
                    
                    # 2. Chunk transcript into ~250 words
                    words = transcript.split()
                    chunk_size = 250
                    for i in range(0, len(words), chunk_size):
                        chunk_text = " ".join(words[i:i+chunk_size])
                        global_text = f"Article Title: {session.title} | Session ID: {session_id} | Content: {chunk_text}"
                        
                        # upload chunk to global memory
                        requests.post(
                            "https://api.hydradb.com/memories/add_memory", 
                            json={
                                "tenant_id": "global_videowiki_tenant",
                                "sub_tenant_id": "main",
                                "memories": [{"text": global_text, "infer": True}]
                            }, 
                            headers=hydradb.get_headers(), 
                            timeout=10
                        )
                except Exception as global_err:
                    print(f"Failed to upload to global tenant: {global_err}")
                
            # Step 7: Update DB record status
            session.hydra_ok = hydra_created and hydra_stored
            session.status = "processing"  # keep processing until article is synthesized!
            db.session.commit()
            
            # Step 8: Emit Hydra done
            if session.hydra_ok:
                emit("hydra", "done", "Stored in HydraDB")
            else:
                emit("hydra", "done", "Stored transcript locally (HydraDB skipped)")
                
            # Wikipedia Article Synthesis
            emit("article", "active", "Synthesizing full Wikipedia-style article using Mistral Large...")
            try:
                article_content = mistral.generate_wikipedia_article(transcript, session.title)
                
                # Re-fetch session in session state context to ensure safety
                session.article_content = article_content
                session.status = "ready"
                db.session.commit()
                emit("article", "done", "Wikipedia article successfully generated!")
            except Exception as article_err:
                print(f"Failed to generate article: {article_err}")
                session.status = "ready"
                db.session.commit()
                emit("article", "done", "Stored raw transcript only (Article generation failed)")
                
            # Step 9: Emit done
            emit("done", "done", session_id=session_id)
            
        except Exception as e:
            # Rollback database on error
            db.session.rollback()
            try:
                session = db.session.get(VideoSession, session_id)
                if session:
                    session.status = "error"
                    session.error_msg = str(e)
                    db.session.commit()
            except Exception as db_err:
                print(f"Failed to update error status for session {session_id}: {db_err}")
                
            emit("error", "error", msg=str(e))

# ==========================================
# FLASK WEB ROUTES
# ==========================================

@app.route("/")
def index():
    """Renders index.html (upload page) with all sessions passed to the sidebar."""
    sessions = VideoSession.query.order_by(VideoSession.created_at.desc()).all()
    return render_template("index.html", sessions=sessions, page="upload")

@app.route("/session/<id>")
def session_detail(id):
    """Renders chat.html for the given session with all sessions passed to the sidebar."""
    sessions = VideoSession.query.order_by(VideoSession.created_at.desc()).all()
    session = db.session.get(VideoSession, id)
    if not session:
        return redirect(url_for("index"))
        
    # Failsafe: if status is ready but article_content is empty/null,
    # generate it on the fly using our mistral generator so there is NEVER an empty article!
    if session.status == "ready" and (not session.article_content or session.article_content.strip() == ""):
        try:
            # Let's generate it synchronously so it's cached!
            article_content = mistral.generate_wikipedia_article(session.transcript or "", session.title)
            session.article_content = article_content
            db.session.commit()
        except Exception as article_err:
            print(f"Failsafe article generation failed for session {id}: {article_err}")
            
    return render_template("chat.html", sessions=sessions, session=session, page="chat")

# ==========================================
# API ENDPOINTS
# ==========================================

@app.route("/api/ingest/youtube", methods=["POST"])
def ingest_youtube():
    """Accepts JSON {url}, returns {session_id}, starts background processing."""
    data = request.get_json() or {}
    url = data.get("url")
    if not url:
        return jsonify({"error": "YouTube URL is required"}), 400
        
    video_id = transcriber.extract_youtube_id(url)
    if not video_id:
        return jsonify({"error": "Could not extract a valid YouTube video ID. Check the URL."}), 400
        
    title = get_youtube_title(video_id)
    thumbnail = transcriber.get_youtube_thumbnail(video_id)
    
    # 1. Create a DB session record with status="processing"
    session = VideoSession(
        title=title,
        source_type="youtube",
        source_ref=url,
        thumbnail=thumbnail,
        status="processing",
        hydra_ok=False
    )
    db.session.add(session)
    db.session.commit()
    
    # Initialize the queue for SSE events
    status_queues[session.id] = queue.Queue()
    
    # 2. Kick off background processing in a daemon thread
    thread = threading.Thread(
        target=process_session,
        args=(app, session.id, "youtube", url)
    )
    thread.daemon = True
    thread.start()
    
    # 3. Return the session_id immediately
    return jsonify({"session_id": session.id})

@app.route("/api/ingest/file", methods=["POST"])
def ingest_file():
    """Accepts multipart file upload, returns {session_id}, starts background processing."""
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request."}), 400
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected."}), 400
        
    filename = secure_filename(file.filename)
    # Generate unique filename to avoid path collisions
    unique_filename = f"{uuid.uuid4()}_{filename}"
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
    
    try:
        file.save(filepath)
    except Exception as e:
        return jsonify({"error": f"Failed to save file: {str(e)}"}), 500
        
    # 1. Create a DB session record with status="processing"
    session = VideoSession(
        title=filename,
        source_type="file",
        source_ref=filename,
        thumbnail=None,
        status="processing",
        hydra_ok=False
    )
    db.session.add(session)
    db.session.commit()
    
    # Initialize the queue for SSE events
    status_queues[session.id] = queue.Queue()
    
    # 2. Kick off background processing in a daemon thread
    thread = threading.Thread(
        target=process_session,
        args=(app, session.id, "file", filepath)
    )
    thread.daemon = True
    thread.start()
    
    # 3. Return the session_id immediately
    return jsonify({"session_id": session.id})

@app.route("/api/ingest/status/<id>")
def ingest_status(id):
    """SSE stream of processing progress events for a session."""
    def event_generator():
        # Quick precheck
        with app.app_context():
            session = db.session.get(VideoSession, id)
            if not session:
                yield f"data: {json.dumps({'step': 'error', 'msg': 'Session not found'})}\n\n"
                return
                
            # If it's already done or failed before SSE connected
            if session.status == "ready":
                yield f"data: {json.dumps({'step': 'done', 'session_id': id})}\n\n"
                return
            elif session.status == "error":
                yield f"data: {json.dumps({'step': 'error', 'msg': session.error_msg or 'Processing failed'})}\n\n"
                return

        # Listen to queue events
        q = status_queues.get(id)
        if not q:
            # Recreate queue or yield done if state is unknown
            yield f"data: {json.dumps({'step': 'transcribe', 'status': 'active', 'msg': 'Connecting to session...'})}\n\n"
            return
            
        while True:
            try:
                event = q.get(timeout=20)  # timeout to keep connection alive
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("step") in ["done", "error"]:
                    break
            except queue.Empty:
                yield ": keepalive\n\n"
            except GeneratorExit:
                break
                
    response = Response(event_generator(), content_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response

@app.route("/api/chat/<session_id>", methods=["POST"])
def chat(session_id):
    """Accepts JSON {message, history[]}, streams Mistral response via SSE."""
    session = db.session.get(VideoSession, session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
        
    if session.status != "ready":
        return jsonify({"error": "Session is not ready for chat yet"}), 400
        
    data = request.get_json() or {}
    message = data.get("message")
    history = data.get("history", [])
    
    if not message:
        return jsonify({"error": "Message is required"}), 400
        
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
                yield f"data: {json.dumps({'chunk': token})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    response = Response(generate_response(), content_type="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response

@app.route("/api/sessions")
def get_sessions():
    """Returns JSON list of all sessions (for sidebar/UI updating)."""
    sessions = VideoSession.query.order_by(VideoSession.created_at.desc()).all()
    return jsonify([s.to_dict() for s in sessions])

@app.route("/api/session/<id>", methods=["DELETE"])
def delete_session(id):
    """Deletes session from DB + HydraDB if possible."""
    session = db.session.get(VideoSession, id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
        
    # Attempt to delete from HydraDB
    hydradb.delete_tenant(id)
    
    # Remove from DB
    try:
        db.session.delete(session)
        db.session.commit()
        # Clean up queue if it exists in status_queues
        if id in status_queues:
            del status_queues[id]
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Failed to delete session: {str(e)}"}), 500

@app.route("/api/wiki/search", methods=["POST"])
def wiki_search():
    """Performs semantic cross-video vector search across all indexed Video Wikipedia articles."""
    data = request.get_json() or {}
    query = data.get("query")
    if not query:
        return jsonify({"error": "Query is required"}), 400
        
    context = hydradb.recall_context("global_videowiki_tenant", query)
    if not context:
        return jsonify({"results": []})
        
    results = []
    seen_sessions = set()
    
    # primary regex parser: search for "Article Title: (.*?) | Session ID: (.*?) | Content: (.*?)"
    matches = re.finditer(r"Article Title:\s*(.*?)\s*\|\s*Session ID:\s*(.*?)\s*\|\s*Content:\s*(.*?)(?=Article Title:|$)", context, re.DOTALL | re.IGNORECASE)
    
    for match in matches:
        title = match.group(1).strip()
        sid = match.group(2).strip()
        content = match.group(3).strip()
        
        if sid not in seen_sessions:
            seen_sessions.add(sid)
            # Find the match in SQLite DB to ensure it still exists and get the source ref/thumbnail if any
            session = db.session.get(VideoSession, sid)
            thumbnail = session.thumbnail if session else None
            source_type = session.source_type if session else "youtube"
            results.append({
                "session_id": sid,
                "session_title": title,
                "thumbnail": thumbnail,
                "source_type": source_type,
                "snippet": content[:240] + "..." if len(content) > 240 else content
            })
            
    # secondary fallback line parser
    if not results:
        lines = context.split("\n")
        for line in lines:
            if "Article Title:" in line and "Session ID:" in line:
                try:
                    parts = line.split("|")
                    title_part = parts[0].replace("Article Title:", "").strip()
                    sid_part = parts[1].replace("Session ID:", "").strip()
                    content_part = parts[2].replace("Content:", "").strip()
                    
                    if sid_part not in seen_sessions:
                        seen_sessions.add(sid_part)
                        session = db.session.get(VideoSession, sid_part)
                        thumbnail = session.thumbnail if session else None
                        source_type = session.source_type if session else "youtube"
                        results.append({
                            "session_id": sid_part,
                            "session_title": title_part,
                            "thumbnail": thumbnail,
                            "source_type": source_type,
                            "snippet": content_part[:240] + "..." if len(content_part) > 240 else content_part
                        })
                except Exception:
                    pass
                    
    return jsonify({"results": results})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
